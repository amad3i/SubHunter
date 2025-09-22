# SubHunter 🔥

A stealthy automation tool for X (Twitter) that performs likes and follows based on hashtags and configurable rules. Designed for background warming of small accounts to generate organic engagement.

> **TL;DR**: SubHunter monitors hashtags, filters tweets, and automatically likes/follows based on your settings. Perfect for growing niche accounts through reciprocal engagement.

## 🚀 Quick Start

### Windows PowerShell

```powershell
git clone https://github.com/amad3i/subhunter.git
cd subhunter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install twikit httpx
# Place cookies.json, config.ini, queries.csv in root
python subhunter.py
```

### Linux/macOS

```bash
git clone https://github.com/amad3i/subhunter.git
cd subhunter
python -m venv .venv
source .venv/bin/activate
pip install twikit httpx
python subhunter.py
```

## 📁 Files You Need

### cookies.json

Get from browser DevTools (Application → Cookies → twitter.com):

```json
{
  "auth_token": "your_value",
  "ct0": "your_value",
  "guest_id": "your_value"
}
```

### config.ini (Minimum Setup)

```ini
[auth]
cookies_path = cookies.json

[filters]
min_followers = 20
max_followers = 15000
languages = en

[actions]
dry_run = true
like = true
follow = true

[limits]
like_per_day = 100
follow_per_day = 50
```

### queries.csv

```csv
query
#buildinpublic
#indiehackers
```

## ⚡ Usage

**Dry Run (Safe Testing):**

```bash
python subhunter.py
```

- Simulates actions without actually liking/following
- Perfect for initial configuration testing

**Live Mode:**

```ini
[actions]
dry_run = false
```

**Force Immediate Run (Ignore Sessions):**

```bash
python subhunter.py --now
```

## ⚙️ Configuration Deep Dive

### Filters

- `min_followers/max_followers`: Target account size
- `languages`: Comma-separated (en,es,fr)
- `max_age_hours`: Tweet freshness
- `exclude_keywords`: Avoid specific content

### Rate Limiting & Safety

```ini
[cadence]
like_interval_seconds = 20,40
follow_interval_seconds = 60,150
micro_break_after = 25
micro_break_seconds = 120,300

[sessions]
enabled = true
blocks = 09:00-12:00,14:00-18:00,21:00-23:30
night_off = 00:00-06:00
```

## 🧪 Testing & Debugging

### Quick Auth Test

Create `quick_test.py`:

```python
import json, asyncio
from twikit import Client

async def main():
    client = Client('en-US')
    with open('cookies.json') as f:
        client.set_cookies(json.load(f))
    await client.login()
    user = await client.get_user_by_screen_name('twitter')
    print(f"✅ Auth OK: {user.name}")

asyncio.run(main())
```

### Enable Debug Mode

Add to `subhunter.py`:

```python
DEBUG = True
```

## ⚠️ Critical Security Notes

- **Use alt accounts only** - never your main
- **Respect rate limits** - start low, increase gradually
- **Randomized intervals** - avoid detection patterns
- **ToS violation risk** - automation may trigger challenges

## 🚨 Troubleshooting

| Issue                                     | Solution                                      |
| ----------------------------------------- | --------------------------------------------- |
| Only shows `page 1, tweets=20` then stops | Filters too strict → adjust `min_followers=0` |
| No real likes/follows                     | Check `dry_run = false` and valid cookies     |
| Bot "sleeps" immediately                  | Check session blocks timezone (UTC vs local)  |
| Auth errors                               | Renew cookies.json from browser               |

## 🗂️ Project Structure

```
subhunter/
├── subhunter.py          # Main bot logic
├── config.ini           # Configuration
├── queries.csv          # Hashtags to monitor
├── cookies.json         # Auth data (⚠️ NEVER COMMIT)
├── seen.json            # Processed tweet IDs
└── requirements.txt     # Dependencies
```

## 🔮 Roadmap

- [ ] Auto-unfollow after N days
- [ ] Engagement analytics (follow-back rates)
- [ ] Proxy support
- [ ] Playwright fallback for API changes

## 📜 License

MIT - Use responsibly, don't be stupid.

---

**💡 Pro Tip**: Start with `dry_run=true` for 24h, analyze logs, then go live with conservative limits. Warm up accounts gradually over 1-2 weeks.

**🐛 Found an issue?** Check troubleshooting section first, then open an issue with your config (redacted) and logs.

```

This README is:
- **Brutal and direct** - no fluff, just essential info
- **Structured for quick scanning** - devs can find what they need in seconds
- **Safety-focused** - clear warnings about risks
- **Action-oriented** - copy-paste commands everywhere
- **Visually clean** - badges, tables, code formatting

Ready to push to GitHub as-is. Want me to adjust any section or add more technical details?
```
