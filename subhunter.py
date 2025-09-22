import asyncio
import json
import os
import sys
import random
import csv
import configparser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time
from typing import List, Tuple, Optional, Set

# pip install twikit httpx
import httpx
from twikit import Client, TooManyRequests


# ===================== CONFIG =====================

@dataclass
class Settings:
    cookies_path: str
    queries_path: str
    seen_path: str

    # filters
    min_followers: int
    max_followers: int
    languages: List[str]
    max_age_hours: int
    exclude_keywords: List[str]

    # actions
    dry_run: bool
    do_like: bool
    do_follow: bool

    # limits (soft caps per "day"/pass)
    like_per_day: int
    follow_per_day: int

    # cadence
    like_interval: Tuple[int, int]
    follow_interval: Tuple[int, int]
    micro_break_after: int
    micro_break_seconds: Tuple[int, int]

    # sessions
    sessions_enabled: bool
    tz: timezone
    session_blocks: List[Tuple[time, time]]
    night_off: Optional[Tuple[time, time]]


def _parse_time_hhmm(s: str) -> time:
    h, m = s.strip().split(":")
    return time(hour=int(h), minute=int(m))


def _strip_inline_comments(s: str) -> str:
    # режем инлайн-комменты ; или #
    return s.split(";", 1)[0].split("#", 1)[0].strip()


def _parse_range_pair(s: str) -> Tuple[int, int]:
    s = _strip_inline_comments(s)
    a, b = s.split(",")
    a, b = int(a.strip()), int(b.strip())
    if a > b:
        a, b = b, a
    return a, b


def _parse_blocks(csv_str: str) -> List[Tuple[time, time]]:
    out: List[Tuple[time, time]] = []
    csv_str = _strip_inline_comments(csv_str or "")
    if not csv_str:
        return out
    for chunk in csv_str.split(","):
        rng = chunk.strip()
        if not rng:
            continue
        left, right = [x.strip() for x in rng.split("-")]
        out.append((_parse_time_hhmm(left), _parse_time_hhmm(right)))
    return out


def load_settings(path: str) -> Settings:
    cfg = configparser.ConfigParser(inline_comment_prefixes=(";", "#"))
    cfg.read(path, encoding="utf-8")

    # sessions / tz
    tzname = cfg.get("sessions", "timezone", fallback="utc").lower()
    tz = timezone.utc if tzname == "utc" else timezone.utc  # оставим UTC по умолчанию

    night_off_str = cfg.get("sessions", "night_off", fallback="").strip()
    night_off: Optional[Tuple[time, time]] = None
    if night_off_str:
        l, r = [x.strip() for x in night_off_str.split("-")]
        night_off = (_parse_time_hhmm(l), _parse_time_hhmm(r))

    languages = [
        x.strip().lower()
        for x in cfg.get("filters", "languages", fallback="en").split(",")
        if x.strip()
    ]
    exclude_keywords = [
        x.strip().lower()
        for x in cfg.get("filters", "exclude_keywords", fallback="").split(",")
        if x.strip()
    ]

    return Settings(
        cookies_path=cfg.get("auth", "cookies_path"),
        queries_path=cfg.get("io", "queries_path"),
        seen_path=cfg.get("io", "seen_path", fallback="seen.json"),

        min_followers=cfg.getint("filters", "min_followers", fallback=0),
        max_followers=cfg.getint("filters", "max_followers", fallback=1000),
        languages=languages or ["en"],
        max_age_hours=cfg.getint("filters", "max_age_hours", fallback=24),
        exclude_keywords=exclude_keywords,

        dry_run=cfg.getboolean("actions", "dry_run", fallback=False),
        do_like=cfg.getboolean("actions", "like", fallback=True),
        do_follow=cfg.getboolean("actions", "follow", fallback=True),

        like_per_day=cfg.getint("limits", "like_per_day", fallback=1500),
        follow_per_day=cfg.getint("limits", "follow_per_day", fallback=333),

        like_interval=_parse_range_pair(cfg.get("cadence", "like_interval_seconds", fallback="20,40")),
        follow_interval=_parse_range_pair(cfg.get("cadence", "follow_interval_seconds", fallback="60,150")),
        micro_break_after=cfg.getint("cadence", "micro_break_after", fallback=25),
        micro_break_seconds=_parse_range_pair(cfg.get("cadence", "micro_break_seconds", fallback="120,300")),

        sessions_enabled=cfg.getboolean("sessions", "enabled", fallback=False),
        tz=tz,
        session_blocks=_parse_blocks(cfg.get("sessions", "blocks", fallback="09:00-12:00,19:00-23:00,23:30-06:00")),
        night_off=night_off,
    )


# ===================== QUERIES =====================

def load_queries(path: str) -> List[str]:
    if not os.path.exists(path):
        print(f"❌ queries file not found: {path}")
        return []
    phrases: List[str] = []
    name = os.path.basename(path).lower()
    if name.endswith(".csv"):
        with open(path, "r", encoding="utf-8", newline="") as f:
            # поддержим и хедер "query", и просто первый столбец
            sample = f.read(2048)
            f.seek(0)
            has_header = False
            try:
                has_header = csv.Sniffer().has_header(sample)
            except Exception:
                pass
            rdr = csv.reader(f)
            idx = 0
            if has_header:
                header = next(rdr, [])
                lheader = [h.strip().lower() for h in header]
                idx = lheader.index("query") if "query" in lheader else 0
            for row in rdr:
                if not row:
                    continue
                q = (row[idx] or "").strip()
                if q:
                    phrases.append(q)
    else:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                phrases.append(s)

    # уникализация
    out, seen = [], set()
    for q in phrases:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


# ===================== FILTERS =====================

def within_blocks(now: datetime, blocks: List[Tuple[time, time]], night_off: Optional[Tuple[time, time]]) -> bool:
    """Смотрим только по локальному времени (без tz-info), чтобы не ловить naive/aware сравнения."""
    t = now.time()

    # night off
    if night_off:
        start, end = night_off
        if start <= end:
            if start <= t <= end:
                return False
        else:  # через полночь
            if t >= start or t <= end:
                return False

    if not blocks:
        return True

    for b_start, b_end in blocks:
        if b_start <= b_end:
            if b_start <= t <= b_end:
                return True
        else:  # через полночь
            if t >= b_start or t <= b_end:
                return True
    return False


def is_rt_text(text: str) -> bool:
    s = text.strip()
    return s.startswith("RT @") or s.startswith("QT @")


def is_reply_text(text: str) -> bool:
    return text.strip().startswith("@")


def ok_lang(lang: Optional[str], allowed: List[str]) -> bool:
    if not lang:
        return True
    return lang.lower() in allowed


def ok_age(created_at, max_age_hours: int) -> bool:
    if not created_at:
        return True
    try:
        dt = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at))
    except Exception:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - dt
    return age <= timedelta(hours=max_age_hours)


def ok_author(user, min_f: int, max_f: int) -> bool:
    followers = getattr(user, "followers_count", None) or getattr(user, "followers", None)
    try:
        followers = int(followers)
    except Exception:
        return True
    return min_f <= followers <= max_f


def ok_keywords(text: str, blacklist: List[str]) -> bool:
    low = text.lower()
    return not any(bad in low for bad in blacklist)


# ===================== ACTIONS =====================

async def act_like(client: Client, tweet_id: str, dry: bool) -> str:
    if dry:
        return "like(dry)"
    try:
        fn = getattr(client, "like_tweet", None) or getattr(client, "favorite_tweet", None)
        if fn is None:
            return "like(n/a)"
        await fn(tweet_id)
        return "like(ok)"
    except TooManyRequests:
        wait = random.randint(45, 90)
        print(f"⏳ Rate limit on LIKE → sleep {wait}s")
        await asyncio.sleep(wait)
        return "like(rate)"
    except Exception as e:
        return f"like(err:{e})"


async def act_follow(client: Client, user_id: str, dry: bool) -> str:
    if dry:
        return "follow(dry)"
    try:
        fn = getattr(client, "follow_user", None) or getattr(client, "create_friendship", None)
        if fn is None:
            return "follow(n/a)"
        await fn(user_id)
        return "follow(ok)"
    except TooManyRequests:
        wait = random.randint(45, 90)
        print(f"⏳ Rate limit on FOLLOW → sleep {wait}s")
        await asyncio.sleep(wait)
        return "follow(rate)"
    except Exception as e:
        return f"follow(err:{e})"


# ===================== CORE LOOP =====================

async def gather_for_query(client: Client,
                           query: str,
                           st: Settings,
                           seen_ids: Set[str],
                           counts: dict):
    print(f"\n🔎 Query: {query}")
    try:
        results = await client.search_tweet(query, product="Latest")
    except Exception as e:
        print(f"❌ search error: {e}")
        return

    page = 0
    while results:
        page += 1
        tweets = list(results)
        print(f"{datetime.now().isoformat(timespec='seconds')} — page {page}, tweets={len(tweets)}")

        for t in tweets:
            tid = getattr(t, "id", None)
            if not tid or tid in seen_ids:
                continue

            text = (getattr(t, "full_text", None) or getattr(t, "text", "") or "").replace("\n", " ").strip()
            if not text or is_rt_text(text) or is_reply_text(text):
                continue
            if not ok_keywords(text, st.exclude_keywords):
                continue
            if not ok_lang(getattr(t, "lang", None), st.languages):
                continue
            if not ok_age(getattr(t, "created_at", None), st.max_age_hours):
                continue

            user = getattr(t, "user", None)
            if not user or not ok_author(user, st.min_followers, st.max_followers):
                continue

            seen_ids.add(tid)  # пометили, чтобы не повторять

            # дневные лимиты
            like_left = st.like_per_day - counts["like"]
            follow_left = st.follow_per_day - counts["follow"]

            # LIKE
            if st.do_like and like_left > 0:
                res = await act_like(client, tid, st.dry_run)
                if res.startswith("like(ok)"):
                    counts["like"] += 1
                await asyncio.sleep(random.randint(*st.like_interval))

            # FOLLOW
            if st.do_follow and follow_left > 0:
                uid = str(getattr(user, "id", "") or getattr(user, "id_str", ""))
                if uid:
                    res = await act_follow(client, uid, st.dry_run)
                    if res.startswith("follow(ok)"):
                        counts["follow"] += 1
                    await asyncio.sleep(random.randint(*st.follow_interval))

            # микро-брейки — по сумме действий
            total = counts["like"] + counts["follow"]
            if st.micro_break_after > 0 and total > 0 and (total % st.micro_break_after == 0):
                pause = random.randint(*st.micro_break_seconds)
                print(f"🛑 micro-break {pause}s")
                await asyncio.sleep(pause)

        # пагинация
        try:
            await asyncio.sleep(random.randint(2, 5))
            results = await results.next()
        except TooManyRequests:
            wait = random.randint(60, 120)
            print(f"⏳ Rate limit on search → sleep {wait}s")
            await asyncio.sleep(wait)
        except Exception as e:
            print(f"⚠️ pagination error: {e}")
            break


async def run_once(st: Settings):
    # сессии / «тихий час»
    now = datetime.now(st.tz)
    if st.sessions_enabled and not within_blocks(now, st.session_blocks, st.night_off):
        print("🌙 outside of session window → sleeping 15m")
        await asyncio.sleep(15 * 60)
        return

    client = Client(language="en-US")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=30)) as http:
        client.http = http

        with open(st.cookies_path, "r", encoding="utf-8") as f:
            client.set_cookies(json.load(f))
        print("✅ cookies loaded")

        queries = load_queries(st.queries_path)
        if not queries:
            print("❌ no queries!")
            return

        # seen
        seen_ids: Set[str] = set()
        if os.path.exists(st.seen_path):
            try:
                with open(st.seen_path, "r", encoding="utf-8") as f:
                    seen_ids = set(json.load(f))
            except Exception:
                seen_ids = set()

        counts = {"like": 0, "follow": 0}

        for q in queries:
            await gather_for_query(client, q, st, seen_ids, counts)

        # сохраняем seen
        try:
            with open(st.seen_path, "w", encoding="utf-8") as f:
                json.dump(list(seen_ids), f)
        except Exception as e:
            print(f"⚠️ cannot write seen.json: {e}")

        print(f"✅ pass done. like={counts['like']} follow={counts['follow']} dry_run={st.dry_run}")


async def main():
    cfg_path = "config.ini"
    if len(sys.argv) > 1:
        cfg_path = sys.argv[1]
    st = load_settings(cfg_path)

    # бесконечно: скрипт работает весь день, с паузами и сессиями
    while True:
        try:
            await run_once(st)
        except Exception as e:
            print(f"💥 fatal in run_once: {e}")
        await asyncio.sleep(random.randint(20, 45))


if __name__ == "__main__":
    asyncio.run(main())
