# 🎓 APPX Course Bot — Telegram-First Authorized Course Management & Media Bot

PRD v2.1 ke mutabik complete implementation. Telegram hi poori user interface hai —
website/admin panel ki zarurat nahi.

## ✨ Features (MVP — sab PRD section 44 success criteria)

| Feature | PRD |
|---|---|
| 🔐 Telegram login (Institute + ID + Password) | §1, §2 |
| 🔑 Password **kabhi store/log nahi hota** (DB me column hi nahi) | §2, §21 |
| 🔒 Encrypted session storage (Fernet) + expiry | §3 |
| 🔑 `/token` — apna session JWT/access token (login se extract, DM me) | §3 |
| 📚 Course list + details (videos/pdfs/chapters counts) | §6, §7 |
| 📋 Content tree (chapters → items) browse + pagination | §8, §9 |
| 📄 TXT export — complete / videos-only / PDFs-only / selected chapters / multi-course | §10-12, §34-35 |
| 🔗 TXT reference modes — `base` (safe) ya `full` (signed working links) | §10 |
| 🎬 m3u8/HLS support — ffmpeg remux (content-type detect) | §13, §37 |
| 🛡 DRM detection → clean fail, job continue + Retry/Skip | §13, §18 |
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

## 🚂 Railway Deployment

> Repo me `Dockerfile` hai — Railway use automatically detect karke build karega
> (ffmpeg included). Bot polling-based hai, koi public URL zaroori nahi;
> `PORT` variable se optional health-check server chalta hai.

### Railway UI me settings:

| Setting | Value |
|---|---|
| **Source** | GitHub repo: `loginyttg-web/Apppx-txt-maker-then-uploader` |
| **Root Directory** | *(khaali chhodo — repo root)* |
| **Build** | Auto (Dockerfile detect hota hai; kuch nahi bharna) |
| **Start Command** | `python main.py` |
| **Volume** | Mount path: `/app/data` (SQLite DB persist karne ke liye) |

### Railway Variables (add all):

```env
BOT_TOKEN=123456:AAH-xxxx            # @BotFather se — REQUIRED
ADMIN_IDS=1234567890                 # aapka telegram id (optional)
PLATFORM_MODE=live                   # live ya mock (test ke liye)
ENCRYPTION_KEY=<Fernet key>          # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
DATABASE_PATH=/app/data/appx.db
EXPORT_DIR=/tmp/appx/exports
JOB_DIR=/tmp/appx/jobs
MAX_ACTIVE_JOBS=3
MAX_JOBS_PER_USER=3
MAX_RETRIES=3
FILE_TTL_HOURS=24
LOG_LEVEL=INFO
PORT=8000                            # optional — health check (/health)
```

Optional platform overrides (agar aapke tenant ke paths alag hain):

```env
PLATFORM_BASE_URL=https://aashapi.appx.co.in
PLATFORM_LOGIN_PATH=/api/v1/login
PLATFORM_COURSES_PATH=/api/v1/user/courses
PLATFORM_CONTENT_PATH=/api/v1/course/{course_id}/content
```

Deploy hone ke baad apne bot ko Telegram par `/start` karke test karein.
Logs Railway dashboard ke **Deploy Logs** me dekhein.

## 🔧 Environment variables

Sab `.env.example` me documented hain. Important:

| Variable | Default | Meaning |
|---|---|---|
| `BOT_TOKEN` | — | @BotFather token (live mode me required) |
| `ADMIN_IDS` | — | Owner/admin Telegram IDs — `/admin` access |
| `UPLOAD_CHANNEL_ID` | — | Files (media + TXT) is channel me jayengi; bot ko channel me admin hona chahiye |
| `SHOW_SESSION_TOKEN` | `yes` | Login ke baad user ko apna session JWT DM me dikhao |
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
| `TXT_REFERENCE_MODE` | `base` | `base` = host+path (signed params hatao) · `full` = signed URL bhi (working links) |
| `FILE_TTL_HOURS` | `24` | Temp file TTL |

> **Note:** Agar aapke platform ke real API paths defaults se alag hain, to unhe
> `.env` me set karein — response JSON ke common shapes (data/result/payload,
> token/access_token/jwt) client automatically normalize karta hai.

## 📄 TXT export — links kaise hongi?

TXT me har item ke saath `Authorized reference:` likhi jati hai. Kaunsi link
milti hai ye `TXT_REFERENCE_MODE` par depend karta hai:

```txt
APPX COURSE
============

Course: Physics

Chapter 01
----------

VIDEO 01
Title: Motion
Type: video
Authorized reference: https://cdn.classx.co.in/media/phy/01/motion.mp4
```

- **`base` (default):** sirf `host/path` — signed query params (`?token=..&sig=..`)
  TXT me nahi jate. Signed URL wale platforms par ye link akele kaam nahi
  karegi — wo ek identifier/reference hai. Media ke liye job system use karo.
- **`full`:** complete platform-provided reference — signed URL bhi included,
  isliye **working links** milengi. TXT ke header me note hota hai:
  *"links sirf account-owner ke personal authorized use ke liye; expire ho
  sakti hain"*. Password/session token/cookies kabhi nahi — sirf media
  reference.
- **Best practice:** TXT = index/reference list. Actual download ke liye
  `[⚙️ Create Media Job]` — authorized session ke saath, isliye signed URL
  expire hone par bhi kaam karta hai.

## 🎬 m3u8 / HLS links kaise handle hoti hain?

1. **TXT export:** reference sanitized likhi jati hai (base mode me
   `https://host/path/stream.m3u8`).
2. **Media job:** HLS detect hota hai jab URL `.m3u8`/`.m3u` se end ho YA
   response Content-Type HLS ho (extension ke bina bhi, e.g. `/playlist?token=..`).
3. ffmpeg se remux:
   ```bash
   ffmpeg -i "<m3u8 url>" -c copy -bsf:a aac_adtstoasc output.mp4
   ```
   `-c copy` = re-encode nahi, sirf remux (fast, CPU-light) → mp4 Telegram par
   upload → temp files delete.
4. ffmpeg nahi hai to clean error: *"HLS processing requires ffmpeg."*
   (Docker image me ffmpeg pre-installed hai.)

## 🛡 DRM-protected content ka kya hota hai?

- Reference me DRM indicators detect hote hain: `widevine`, `playready`,
  `fairplay`, `clearkey`, license server, `.mpd`, `drm=...`
- Response: `❌ Media cannot be processed through the available authorized
  method.` (code: `drm_protected`)
- **Bypass kabhi nahi** — PRD §13/§43 hard rule hai (ye illegal hai: DMCA
  §1201 / India Copyright Act §65A TPM-circumvention offense hai; account
  hona ya bug-bounty kaam karna isse legal nahi banata).
- Bug-bounty/testing wale: vulnerability report karte waqt mass content
  extract nahi karte — chhota PoC (1-2 items) + report kafi hai.
- Item fail → job **continue** karta hai → `[🔄 Retry] [⏭️ Skip] [📊 Job Status]`.

## 📢 Channel delivery (`UPLOAD_CHANNEL_ID`)

- Set karo to **media jobs ki files** aur **TXT exports** us channel me
  jayengi — user DM ke bajaye.
- Progress updates + final summary + failed-item notifications hamesha
  **user ke DM** me rehte hain.
- Bot ko channel me **admin** hona chahiye (channel id `@userinfobot` se lo).
- Note: Telegram **bot** upload limit ~50MB hai; bade files ke liye
  local Bot API server ya userbot path (PRD §37) use karein.

## 🔍 Course ke andar "classes" kaise find hote hain?

Client response ke common keys ko automatically detect karta hai:

- **Chapters/classes:** `chapters, modules, sections, units, topics, batches, classes`
- **Items:** `items, content, videos, pdfs, resources, lectures, lessons, classes, sessions`
- **Titles:** `title, name, subject, topic, label` · **IDs:** `id, course_id, uuid, video_id`
- **Media refs:** `secure_url, video_url, m3u8, hls_url, stream_url, pdf_url, file_url, download_url, link`

Agar aapke platform ka structure alag hai → `PLATFORM_*` paths/keys `.env` me
override karo.

## 🔑 Apna session JWT kaise milega?

Aapke paas cookie/token/key nahi hai — koi baat nahi. Bot login karte waqt
platform ke response se **token automatically extract** karta hai:

- **Login ke turant baad:** agar `SHOW_SESSION_TOKEN=yes` (default) to
  `🔑 Session Token` message DM me aata hai — JWT/access token, refresh token
  (agar platform de), cookies (agar platform cookie-auth use kare), expiry,
  institute, account.
- **Kabhi bhi:** `/token` command ya Account menu me `[🔑 Session Token]` button.
- Token JSON me kahan hai — configurable: `PLATFORM_TOKEN_JSON_PATH`
  (default `data.token, data.access_token, data.jwt, token, ...`); agar
  platform header me token de (Authorization) ya cookie me (`token`/`jwt`),
  wo bhi auto-detect hota hai.
- **Security:** token sirf usi user ke DM me jata hai (ownership check);
  DB me encrypted rehta hai; TXT/logs me kabhi nahi; password kabhi nahi.
- ⚠️ Token sensitive hai — share na karein; expire hone par `/login` se naya.

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
python main.py --selftest      # 22 end-to-end checks (login→jobs→cleanup→DRM→signed URLs)
python tests/smoke_bot.py      # Telegram UI flow (mocked bot)
python main.py --check         # config + registry check
```

## 📈 Roadmap (PRD §45)

Phase 2 (future): parallel workers, admin panel, analytics, scheduling,
distributed workers, multiple bot instances, advanced monitoring.
