"""
Message templates — sab messages yahan se (single source of truth).
HTML parse mode use hota hai.
"""
from __future__ import annotations

from datetime import datetime

from platforms.models import Course, SessionData, Tenant
from utils.helpers import human_duration, human_size

WELCOME = (
    "👋 <b>Welcome to APPX Course Bot</b>\n\n"
    "🔐 Login with your authorized course account.\n"
    "Apne institute ka naam, course ID aur password se login karein — "
    "uske baad courses, content list (TXT) aur authorized media sab "
    "Telegram par milega."
)

LOGIN_INSTITUTE = (
    "🏫 <b>Institute select karein</b>\n\n"
    "Apne coaching/institute ka naam type karein "
    "(jaise <i>Lakshya</i>, <i>Physics Wallah</i>...)\n\n"
    "Ya phir niche se manual API URL option choose karein."
)

LOGIN_MANUAL_URL = (
    "🔗 <b>Manual API URL</b>\n\n"
    "Apne institute ki API base URL type karein, jaise:\n"
    "<code>https://aashapi.appx.co.in</code>"
)

LOGIN_USERNAME = "🔐 Apna <b>Course ID / Username</b> bhejiye:"
LOGIN_PASSWORD = (
    "🔑 <b>Password bhejiye</b>\n\n"
    "⚠️ Security note: Password humare database ya logs me <b>kabhi store nahi hota</b> — "
    "sirf authentication ke liye use hota hai."
)

LOGIN_AUTHENTICATING = "⏳ Authenticating..."

LOGIN_FAILED = "❌ <b>Login failed.</b>\n\nPlease check your ID/password."

MENU = (
    "🏠 <b>APPX Course Bot</b>\n\n"
    "Neeche se choose karein:"
)

ACCOUNT = (
    "👤 <b>Account</b>\n\n"
    "• Telegram ID: <code>{tg_id}</code>\n"
    "• Platform User: <b>{name}</b>\n"
    "• Institute: <b>{tenant_name}</b>\n"
    "• Username: <code>{username}</code>\n"
    "• Session expiry: {expiry}\n"
    "• Courses: <b>{courses}</b>\n\n"
    "Session encrypted reference ke roop me store hota hai. "
    "Password kabhi store nahi hota."
)

COURSES_HEADER = "📚 <b>YOUR COURSES</b>\n\n"

COURSE_DETAIL = (
    "📚 <b>{title}</b>\n\n"
    "🎬 Videos: {videos}\n"
    "📄 PDFs: {pdfs}\n"
    "📂 Chapters: {chapters}"
)

CONTENT_HEADER = "📚 <b>{title}</b>\n\n"

EXPORT_OPTIONS = (
    "📄 <b>Export Options</b>\n"
    "<i>{course}</i>\n\n"
    "Select karein:"
)

EXPORT_SELECT_CHAPTERS = (
    "📂 <b>Select Chapters</b>\n"
    "<i>{course}</i>\n\n"
    "☑ = selected | ☐ = not selected\n"
    "Select karne ke baad [Generate TXT] dabayein."
)

EXPORT_MULTI = (
    "📄 <b>Multi-Course Export</b>\n\n"
    "Courses select karein (☑/☐), phir [Generate]:\n\n"
    "EXPORT_MODE=<code>{mode}</code> — "
    "{mode_hint}"
)

JOB_SCOPE = (
    "⚙️ <b>Create Media Job</b>\n"
    "<i>{course}</i>\n\n"
    "Chapters select karein (☑ = selected).\n"
    "Job sequentially process hoga — har item download → upload → delete."
)

JOB_CREATED = (
    "⚙️ <b>Job Created</b>\n\n"
    "Job ID: <code>{job_id}</code>\n"
    "Course: {course}\n"
    "Items: {total}\n"
    "Status: ⏳ Queued"
)

JOB_NOT_FOUND = "❌ Job nahi mila ya aapke paas iski access nahi hai."

JOB_CANCEL_CONFIRM = "⚠️ Cancel this job?\n\n<code>{job_id}</code> — {course} ({status})"

JOB_CANCELLED = "🚫 <b>Job cancelled.</b>\n\n<code>{job_id}</code>"

JOBS_HEADER = "⚙️ <b>JOB HISTORY</b>\n\n"

JOBS_EMPTY = "📭 Abhi koi job nahi hai.\n\nCourse kholkar [⚙️ Create Media Job] dabayein."

STATUS_HEADER = "⚙️ <b>ACTIVE JOBS</b>\n\n"

STATUS_EMPTY = "✅ Koi active job nahi hai."

LOGOUT_CONFIRM = "🚪 <b>Logout</b>\n\nAre you sure?\n\nSession + temporary files clear ho jayenge."

LOGGED_OUT = "✅ <b>Logged out successfully.</b>"

SESSION_EXPIRED = (
    "⚠️ <b>Session expired.</b>\n\n"
    "Please login again."
)

HELP = (
    "📖 <b>APPX Course Bot — Help</b>\n\n"
    "Commands:\n"
    "/start — welcome / menu\n"
    "/login — login flow\n"
    "/courses — meri courses\n"
    "/content — course content\n"
    "/export — TXT export\n"
    "/jobs — job history\n"
    "/status — active jobs\n"
    "/cancel — job cancel\n"
    "/logout — logout\n"
    "/help — yeh help\n\n"
    "Primary interaction inline buttons se hota hai.\n\n"
    "🔒 Passwords kabhi store/log nahi hote.\n"
    "⚠️ Sirf authorized content process hota hai — DRM bypass nahi."
)

ADMIN_STATS = (
    "🛡 <b>ADMIN STATS</b>\n\n"
    "👥 Users: {users}\n"
    "🔑 Active sessions: {active_sessions}\n"
    "⚙️ Active jobs: {active_jobs}\n"
    "📭 Queue size: {queue}\n"
    "❌ Failed jobs: {failed_jobs}\n"
    "❌ Failed items: {failed_items}\n"
    "📦 Total jobs: {total_jobs}\n"
    "💾 Temp storage: {storage}\n\n"
    "⚠️ API errors: {api_errors}\n"
    "⚠️ Telegram errors: {tg_errors}"
)

EXPORT_STARTED = "⏳ Generating content list...\n\n<i>{course}</i>"

EXPORT_READY = "📄 <b>Your TXT file is ready.</b>"

EXPORT_ERROR = "❌ <b>Export failed.</b>\n\n{reason}"

BUSY = "⏳ Server is currently busy.\n\nAapka job queue me add ho gaya hai."

def login_success(name: str, tenant: str, courses: int) -> str:
    return (
        "✅ <b>Login Successful</b>\n\n"
        f"👤 Account: {name}\n"
        f"🏫 Institute: {tenant}\n"
        f"📚 Available Courses: {courses}"
    )


def fmt_expiry(ts: int) -> str:
    if not ts:
        return "unknown"
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M")


def fmt_course(course: Course) -> str:
    meta = course.meta or {}
    parts = []
    if meta.get("videos"):
        parts.append(f"🎬 {meta['videos']}")
    if meta.get("pdfs"):
        parts.append(f"📄 {meta['pdfs']}")
    if meta.get("chapters"):
        parts.append(f"📂 {meta['chapters']}")
    suffix = "  " + " | ".join(parts) if parts else ""
    return f"{course.title}{suffix}"
