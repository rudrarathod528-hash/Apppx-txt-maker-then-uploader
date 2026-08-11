# 🎓 APPX Course Bot — Telegram-First Authorized Course Management & Media Bot

PRD v2.1 ke mutabik complete implementation. Telegram hi poori user interface hai —
website/admin panel ki zarurat nahi.

## ✨ Features (MVP — sab PRD section 44 success criteria)

| Feature | PRD |
|---|---|
| 🔐 Telegram login (Institute + ID + Password) | §1, §2 |
| 🔑 Password **kabhi store/log nahi hota** (DB me column hi nahi) | §2, §21 |
| 🔒 Encrypted session storage (Fernet) + expiry | §3 |
| 📚 Course list + details (videos/pdfs/chapters counts) | §6, §7 |
| 📋 Content tree (chapters → items) browse + pagination | §8, §9 |
| 📄 TXT export — complete / videos-only / PDFs-only / selected chapters / multi-course | §10-12, §34-35 |
| 📤 TXT Telegram document delivery + temp delete | §11 |
| ⚙️ Media jobs — chapter selection → queue → sequential worker | §14-15 |
| 📊 Progress message (edit, nayi message nahi) | §16 |
| 🔄 Retry engine (auto 3x + manual Retry/Skip) | §17-18 |
| 🚫 Job cancel + ownership validation (User A ↔ User B kabhi nahi) | §23, §28 |
| 🧹 TTL cleanup worker (24h) + old job prune | §20 |
| 🚪 Logout (session revoke + clear + temp files delete) | §24 |
| ⚙️ /jobs history, /status, /cancel, /admin stats | §26-27, §40 |
| ⏱ Rate limiting (login/export/jobs) | §29, §42 |
| 🏢 2400+ ClassX/AppX tenant registry (appxapis.json) | §41 |
| 🧪 Mock mode — bina real credentials ke pura flow test | §41 |

## 🚀 Quick start

```bash
# 1. dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. config
cp .env.example .env
# .env me BOT_TOKEN (aur chaaho to ADMIN_IDS) bharo

# 3. selftest (bina Telegram ke — sab kuch verify hota hai)
python main.py --selftest

# 4. run
python main.py
```

### Demo mode (koi real credentials nahi chahiye)

`.env` me:

```
PLATFORM_MODE=mock
```

Login: Institute = **Demo Institute**, Username = **demo**, Password = **demo123**.
4 sample courses, TXT exports, media jobs — sab real files ke saath chalega.

### Handler smoke test (mocked Telegram)

```bash
python tests/smoke_bot.py
```

## 🐳 Docker

```bash
docker build -t appx-course-bot .
docker run -d --name appx-bot --env-file .env \
  -v appx-data:/app/data appx-course-bot
```

Image me ffmpeg pre-installed hai (HLS processing ke liye).

## 🔧 Environment variables

Sab `.env.example` me documented hain. Important:

| Variable | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | @BotFather token (live mode me required) |
| `PLATFORM_MODE` | `live` | `live` ya `mock` |
| `PLATFORM_BASE_URL` | — | Single-tenant ho to set karo; warna registry se auto |
| `PLATFORM_LOGIN_PATH` | `/api/v1/login` | Login endpoint path |
| `PLATFORM_COURSES_PATH` | `/api/v1/user/courses` | Courses endpoint |
| `PLATFORM_CONTENT_PATH` | `/api/v1/course/{course_id}/content` | Content endpoint |
| `PLATFORM_TOKEN_JSON_PATH` | `data.token,...` | Response me token kahan hai |
| `ENCRYPTION_KEY` | auto | Fernet key (production me set karo!) |
| `MAX_ACTIVE_JOBS` | `5` | Global concurrent jobs |
| `MAX_JOBS_PER_USER` | `3` | Per-user active jobs |
| `MAX_RETRIES` | `3` | Retry attempts |
| `MAX_UPLOAD_MB` | `1950` | Telegram upload limit |
| `EXPORT_MODE` | `single` | `single` = ek file, `separate` = per-course file |
| `FILE_TTL_HOURS` | `24` | Temp file TTL |

> **Note:** Agar aapke platform ke real API paths defaults se alag hain, to unhe
> `.env` me set karein — response JSON ke common shapes (data/result/payload,
> token/access_token/jwt) client automatically normalize karta hai.

## 🔌 ClassX/AppX API adapter

- **Registry** (`platforms/registry.py`): `appxapis.json` se 2400+ tenants load;
  institute name se fuzzy search.
- **Client** (`platforms/client.py`): login → token extraction (configurable JSON
  paths) → courses → content tree → media references. Response shapes
  case-insensitive deep-lookup se normalize hote hain.
- **Mock** (`platforms/mock.py`): demo platform + sample media (valid PDF; MP4
  ffmpeg ho to real, warna text sample).
- Media download me Authorization header **sirf tenant ke apne host** ko jata hai.

## 🛡 Security design (PRD §22)

- Password: DB me **column hi nahi**; logs me kabhi nahi; memory se turant discard.
- Session reference: Fernet-encrypted; expiry check har request par.
- Logging: redaction + URLs se query params hatao (signed URLs log nahi hote).
- Ownership: har job/export/course access `telegram_user_id` se verified.
- Rate limits: login 5/5min, export 5/10min, jobs per-user + global.
- Input validation: filenames sanitized, size checks, URL validation.
- **Non-goals:** DRM bypass, credential harvesting, access-control defeat —
  kabhi nahi. Unsupported media → clean error (`unsupported_media`).

## 📁 Project structure

```
├── main.py                  # entry (polling + worker + cleanup + --selftest)
├── config.py                # env config
├── context.py               # DI container
├── bot/                     # handlers, keyboards, messages, states
├── auth/                    # login flow + encrypted session manager
├── platforms/               # ClassX client, registry, normalizer, mock
├── services/                # courses, content, TXT export, media processing
├── jobs/                    # queue, manager, sequential worker (retry/cancel)
├── storage/                 # SQLite + TTL cleanup
├── utils/                   # logger (redaction), security (Fernet/rate-limit), gateway
├── tests/                   # selftest + bot smoke test
├── appxapis.json            # 2400+ tenant registry
└── Project PRD.txt          # improved PRD v2.1
```

## 🧪 Testing

```bash
python main.py --selftest      # 19 end-to-end checks (login→jobs→cleanup)
python tests/smoke_bot.py      # Telegram UI flow (mocked bot)
python main.py --check         # config + registry check
```

## 📈 Roadmap (PRD §45)

Phase 2 (future): parallel workers, admin panel, analytics, scheduling,
distributed workers, multiple bot instances, advanced monitoring.
