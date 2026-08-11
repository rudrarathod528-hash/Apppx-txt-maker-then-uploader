"""Inline keyboard builders."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from platforms.models import ContentTree, Course, Tenant
from utils.helpers import paginate

PER_PAGE_COURSES = 8
PER_PAGE_CHAPTER_ITEMS = 10
PER_PAGE_JOBS = 5


def _row(*buttons: InlineKeyboardButton) -> list[InlineKeyboardButton]:
    return list(buttons)


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(InlineKeyboardButton(text="📚 My Courses", callback_data="m:courses")),
        _row(InlineKeyboardButton(text="📋 Content", callback_data="m:content_pick")),
        _row(InlineKeyboardButton(text="📄 Export TXT", callback_data="m:export")),
        _row(InlineKeyboardButton(text="⚙️ Jobs", callback_data="m:jobs")),
        _row(
            InlineKeyboardButton(text="👤 Account", callback_data="m:account"),
            InlineKeyboardButton(text="🚪 Logout", callback_data="m:logout"),
        ),
    ])


def login_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(InlineKeyboardButton(text="🔐 Login", callback_data="login:start")),
    ])


def inst_results_kb(results: list[Tenant], tg_id: int) -> InlineKeyboardMarkup:
    rows = []
    for i, t in enumerate(results):
        rows.append(_row(InlineKeyboardButton(text=f"🏫 {t.name}", callback_data=f"inst:pick:{i}")))
    rows.append(_row(
        InlineKeyboardButton(text="🔗 Manual URL", callback_data="inst:manual"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="auth:abort"),
    ))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def login_cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(InlineKeyboardButton(text="❌ Cancel", callback_data="auth:abort")),
    ])


def login_retry_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(
            InlineKeyboardButton(text="🔄 Try Again", callback_data="login:start"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="auth:abort"),
        ),
    ])


def courses_kb(courses: list[Course], page: int = 0, action: str = "course:open") -> tuple[InlineKeyboardMarkup, int]:
    items, total_pages, page = paginate(courses, page, PER_PAGE_COURSES)
    rows = []
    for idx, course in enumerate(items):
        global_idx = page * PER_PAGE_COURSES + idx
        rows.append(_row(InlineKeyboardButton(
            text=f"📚 {course.title}", callback_data=f"{action}:{global_idx}"
        )))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"{action}:p:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"{action}:p:{page + 1}"))
    if nav:
        rows.append(_row(*nav))
    rows.append(_row(InlineKeyboardButton(text="🏠 Home", callback_data="m:home")))
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def course_detail_kb(course_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(InlineKeyboardButton(text="📋 View Content", callback_data=f"content:open:{course_idx}")),
        _row(InlineKeyboardButton(text="📄 Generate TXT", callback_data=f"export:opt:{course_idx}")),
        _row(InlineKeyboardButton(text="⚙️ Create Media Job", callback_data=f"job:scope:{course_idx}")),
        _row(InlineKeyboardButton(text="⬅️ Back", callback_data="m:courses")),
    ])


def content_kb(course_idx: int, tree: ContentTree, page: int = 0) -> tuple[InlineKeyboardMarkup, int]:
    items, total_pages, page = paginate(tree.chapters, page, 8)
    rows = []
    for ch_idx, ch in enumerate(items):
        global_idx = page * 8 + ch_idx
        label = f"{ch.title}  🎬 {ch.videos}  📄 {ch.pdfs}"
        rows.append(_row(InlineKeyboardButton(
            text=label, callback_data=f"content:ch:{course_idx}:{global_idx}:0"
        )))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"content:p:{course_idx}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"content:p:{course_idx}:{page + 1}"))
    if nav:
        rows.append(_row(*nav))
    rows.append(_row(
        InlineKeyboardButton(text="📄 Export TXT", callback_data=f"export:opt:{course_idx}"),
        InlineKeyboardButton(text="⚙️ Create Job", callback_data=f"job:scope:{course_idx}"),
    ))
    rows.append(_row(InlineKeyboardButton(text="⬅️ Back", callback_data=f"course:open:{course_idx}")))
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def chapter_items_kb(course_idx: int, chapter_idx: int, items: list, page: int = 0) -> tuple[InlineKeyboardMarkup, int]:
    shown, total_pages, page = paginate(items, page, PER_PAGE_CHAPTER_ITEMS)
    rows = []
    for it in shown:
        icon = "🎬" if it.type == "video" else "📄" if it.type == "pdf" else "📎"
        rows.append(_row(InlineKeyboardButton(
            text=f"{icon} {it.title}", callback_data="chapter:noop"
        )))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"content:ch:{course_idx}:{chapter_idx}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"content:ch:{course_idx}:{chapter_idx}:{page + 1}"))
    if nav:
        rows.append(_row(*nav))
    rows.append(_row(
        InlineKeyboardButton(text="📄 Export TXT", callback_data=f"export:opt:{course_idx}"),
        InlineKeyboardButton(text="⚙️ Create Job", callback_data=f"job:scope:{course_idx}"),
    ))
    rows.append(_row(InlineKeyboardButton(text="⬅️ Back", callback_data=f"content:open:{course_idx}")))
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def export_options_kb(course_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(InlineKeyboardButton(text="📚 Complete Course", callback_data=f"export:kind:{course_idx}:complete")),
        _row(InlineKeyboardButton(text="🎬 Videos Only", callback_data=f"export:kind:{course_idx}:videos")),
        _row(InlineKeyboardButton(text="📄 PDFs Only", callback_data=f"export:kind:{course_idx}:pdfs")),
        _row(InlineKeyboardButton(text="📂 Selected Chapters", callback_data=f"export:ch:{course_idx}:0")),
        _row(InlineKeyboardButton(text="⬅️ Back", callback_data=f"course:open:{course_idx}")),
    ])


def export_chapters_kb(course_idx: int, tree: ContentTree, selected: set[int], page: int = 0) -> tuple[InlineKeyboardMarkup, int]:
    shown, total_pages, page = paginate(tree.chapters, page, 8)
    rows = []
    for ch_idx, ch in enumerate(shown):
        global_idx = page * 8 + ch_idx
        mark = "☑" if global_idx in selected else "☐"
        rows.append(_row(InlineKeyboardButton(
            text=f"{mark} {ch.title}", callback_data=f"export:tgl:{course_idx}:{global_idx}"
        )))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"export:ch:{course_idx}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"export:ch:{course_idx}:{page + 1}"))
    if nav:
        rows.append(_row(*nav))
    rows.append(_row(InlineKeyboardButton(text="📄 Generate TXT", callback_data=f"export:go:{course_idx}")))
    rows.append(_row(
        InlineKeyboardButton(text="✅ Select All", callback_data=f"export:all:{course_idx}"),
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"export:opt:{course_idx}"),
    ))
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def export_multi_kb(courses: list[Course], selected: set[int]) -> InlineKeyboardMarkup:
    rows = []
    for idx, c in enumerate(courses):
        mark = "☑" if idx in selected else "☐"
        rows.append(_row(InlineKeyboardButton(text=f"{mark} {c.title}", callback_data=f"export:mc:{idx}")))
    rows.append(_row(InlineKeyboardButton(text="📄 Generate", callback_data="export:go_mc")))
    rows.append(_row(
        InlineKeyboardButton(text="✅ Select All", callback_data="export:all_mc"),
        InlineKeyboardButton(text="🏠 Home", callback_data="m:home"),
    ))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def job_scope_kb(course_idx: int, tree: ContentTree, selected: set[int], page: int = 0) -> tuple[InlineKeyboardMarkup, int]:
    shown, total_pages, page = paginate(tree.chapters, page, 8)
    rows = []
    for ch_idx, ch in enumerate(shown):
        global_idx = page * 8 + ch_idx
        mark = "☑" if global_idx in selected else "☐"
        rows.append(_row(InlineKeyboardButton(
            text=f"{mark} {ch.title} (🎬{ch.videos} 📄{ch.pdfs})",
            callback_data=f"job:tgl:{course_idx}:{global_idx}",
        )))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"job:scope:{course_idx}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"job:scope:{course_idx}:{page + 1}"))
    if nav:
        rows.append(_row(*nav))
    rows.append(_row(InlineKeyboardButton(text="⚙️ Create Job", callback_data=f"job:mk:{course_idx}")))
    rows.append(_row(
        InlineKeyboardButton(text="✅ Select All", callback_data=f"job:all:{course_idx}"),
        InlineKeyboardButton(text="⬅️ Back", callback_data=f"course:open:{course_idx}"),
    ))
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def job_kb(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(
            InlineKeyboardButton(text="📊 View Status", callback_data=f"job:status:{job_id}"),
            InlineKeyboardButton(text="❌ Cancel", callback_data=f"job:cancel:{job_id}"),
        ),
    ])


def job_detail_kb(job_id: str, active: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if active:
        rows.append(_row(InlineKeyboardButton(text="❌ Cancel", callback_data=f"job:cancel:{job_id}")))
    rows.append(_row(InlineKeyboardButton(text="⬅️ Back", callback_data="m:jobs")))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirm_kb(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(
            InlineKeyboardButton(text="✅ Yes", callback_data=f"job:cc:{job_id}"),
            InlineKeyboardButton(text="❌ No", callback_data=f"job:status:{job_id}"),
        ),
    ])


def failed_item_kb(job_id: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(
            InlineKeyboardButton(text="🔄 Retry", callback_data=f"job:retry:{job_id}:{item_id}"),
            InlineKeyboardButton(text="⏭️ Skip", callback_data=f"job:skip:{job_id}:{item_id}"),
            InlineKeyboardButton(text="📊 Job Status", callback_data=f"job:status:{job_id}"),
        ),
    ])


def jobs_kb(jobs: list[dict], page: int = 0) -> tuple[InlineKeyboardMarkup, int]:
    shown, total_pages, page = paginate(jobs, page, PER_PAGE_JOBS)
    rows = []
    for job in shown:
        icon = {"completed": "✅", "failed": "❌", "cancelled": "🚫",
                "queued": "⏳", "processing": "⚙️"}.get(job["status"], "❓")
        rows.append(_row(InlineKeyboardButton(
            text=f"{icon} {job['job_id']} — {job['course_title']}",
            callback_data=f"job:status:{job['job_id']}",
        )))
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ Previous", callback_data=f"jobs:p:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"jobs:p:{page + 1}"))
    if nav:
        rows.append(_row(*nav))
    rows.append(_row(InlineKeyboardButton(text="🏠 Home", callback_data="m:home")))
    return InlineKeyboardMarkup(inline_keyboard=rows), total_pages


def logout_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        _row(
            InlineKeyboardButton(text="✅ Yes, Logout", callback_data="logout:yes"),
            InlineKeyboardButton(text="❌ Cancel", callback_data="m:home"),
        ),
    ])
