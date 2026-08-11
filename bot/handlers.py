"""
All Telegram handlers — commands + inline callbacks + login FSM.

Ownership: har callback/command me tg_id se hi data access hota hai.
Errors: sanitized (kabhi raw token/password nahi dikhta).
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message

import bot.messages as msg
import bot.keyboards as kb
from bot.states import LoginStates
from context import ctx
from platforms.models import Tenant
from utils.logger import get_logger
from utils.security import AppError, safe_error_message

log = get_logger("handlers")
router = Router()


# ================================================================= helpers

def _data(cb: CallbackQuery) -> list[str]:
    return (cb.data or "").split(":")


async def _edit(cb: CallbackQuery, text: str, markup=None) -> None:
    """Message edit (agar edit fail ho to nayi message bhej)."""
    try:
        await cb.message.edit_text(
            text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    except TelegramAPIError:
        try:
            await cb.message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
        except TelegramAPIError:
            pass


async def _answer(cb: CallbackQuery, text: str | None = None) -> None:
    try:
        await cb.answer(text)
    except TelegramAPIError:
        pass


async def _send(chat_id: int, text: str, markup=None) -> None:
    try:
        await ctx.bot.send_message(
            chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup
        )
    except TelegramAPIError:
        pass


def _require_session(tg_id: int):
    """Session check; nahi to expired message + raise."""
    session = ctx.sessions.get(tg_id)
    if not session:
        raise AppError("unauthorized", msg.SESSION_EXPIRED)
    return session


# ================================================================= commands

@router.message(Command("start", "menu"))
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg_id = message.from_user.id
    session = ctx.sessions.get(tg_id)
    if session:
        await _send(tg_id, msg.MENU, kb.main_menu_kb())
    else:
        await _send(tg_id, msg.WELCOME, kb.login_kb())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _send(message.from_user.id, msg.HELP)


@router.message(Command("login"))
async def cmd_login(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    await state.clear()
    await state.set_state(LoginStates.inst_search)
    text = msg.LOGIN_INSTITUTE
    markup = None
    row = ctx.db.get_user(tg_id)
    if row and row.get("tenant_name"):
        text += f"\n\n<i>Last time: {row['tenant_name']}</i>"
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=f"🔄 {row['tenant_name']} (last)",
                callback_data=f"inst:last:{row.get('tenant_id', '')}",
            )],
            [InlineKeyboardButton(text="🔗 Manual URL", callback_data="inst:manual"),
             InlineKeyboardButton(text="❌ Cancel", callback_data="auth:abort")],
        ])
    await _send(tg_id, text, markup)


@router.message(Command("courses", "mycourses"))
async def cmd_courses(message: Message) -> None:
    tg_id = message.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _send(tg_id, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    if not courses:
        await _send(tg_id, "📭 Aapke paas koi course available nahi hai.")
        return
    markup, _ = kb.courses_kb(courses)
    await _send(tg_id, msg.COURSES_HEADER, markup)


@router.message(Command("content"))
async def cmd_content(message: Message) -> None:
    tg_id = message.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _send(tg_id, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    if not courses:
        await _send(tg_id, "📭 Koi course nahi mila.")
        return
    markup, _ = kb.courses_kb(courses, action="content:open")
    await _send(tg_id, "📋 <b>Content dekhne ke liye course choose karein:</b>", markup)


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    tg_id = message.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _send(tg_id, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    if not courses:
        await _send(tg_id, "📭 Koi course nahi mila.")
        return
    selected = ctx.selection(tg_id, "export_mc")
    mode_hint = "ek hi file me sab courses" if ctx.cfg.export_mode == "single" else "har course ki alag file"
    await _send(
        tg_id,
        msg.EXPORT_MULTI.format(mode=ctx.cfg.export_mode, mode_hint=mode_hint),
        kb.export_multi_kb(courses, selected),
    )


@router.message(Command("jobs"))
async def cmd_jobs(message: Message) -> None:
    await _show_jobs(message.from_user.id, message, 0)


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    tg_id = message.from_user.id
    active = [j for j in ctx.jobs.history(tg_id) if j["status"] in ("queued", "processing")]
    if not active:
        await _send(tg_id, msg.STATUS_EMPTY)
        return
    await _send(tg_id, msg.STATUS_HEADER + "\n".join(
        f"<code>{j['job_id']}</code> — {j['course_title']} ({j['completed']}/{j['total']})"
        for j in active
    ))


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    # login ke dauran /cancel → login abort
    if await state.get_state():
        await state.clear()
        await _send(tg_id, "❌ Login cancelled.", kb.login_kb())
        return
    args = (message.text or "").split()
    if len(args) > 1:
        job_id = args[1].upper()
        try:
            job = ctx.jobs.get_job(job_id, tg_id)
            await _send(tg_id, msg.JOB_CANCEL_CONFIRM.format(
                job_id=job["job_id"], course=job["course_title"], status=job["status"]
            ), kb.cancel_confirm_kb(job_id))
        except AppError as e:
            await _send(tg_id, e.message)
        return
    active = [j for j in ctx.jobs.history(tg_id) if j["status"] in ("queued", "processing")]
    if not active:
        await _send(tg_id, "✅ Koi active job nahi hai.")
        return
    await _send(tg_id, "⚠️ Cancel karne ke liye job choose karein:", kb.jobs_kb(active)[0])


@router.message(Command("logout"))
async def cmd_logout(message: Message) -> None:
    await _send(message.from_user.id, msg.LOGOUT_CONFIRM, kb.logout_kb())


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    tg_id = message.from_user.id
    if tg_id not in ctx.cfg.admin_ids:
        await _send(tg_id, "⛔ Access denied.")
        return
    stats = ctx.db.stats()
    await _send(tg_id, msg.ADMIN_STATS.format(
        **stats,
        queue=ctx.queue.qsize(),
        storage=_temp_storage_hint(),
        api_errors=ctx.stats["api_errors"],
        tg_errors=ctx.stats["tg_errors"],
    ))


def _temp_storage_hint() -> str:
    import shutil
    from pathlib import Path

    total = 0
    for root in (Path(ctx.cfg.export_dir), Path(ctx.cfg.job_dir)):
        if root.exists():
            for f in root.rglob("*"):
                if f.is_file():
                    try:
                        total += f.stat().st_size
                    except OSError:
                        pass
    return f"{total / 1024 / 1024:.1f} MB"


# ================================================================= login FSM

@router.message(StateFilter(LoginStates.inst_search))
async def fsm_inst_search(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    query = (message.text or "").strip()[:100]
    if not query:
        return
    results = ctx.registry.search(query, limit=10)
    if not results:
        await _send(tg_id, "❌ Koi institute nahi mila. Dobara try karein ya Manual URL use karein.")
        return
    ctx.inst_search[tg_id] = results
    await _send(tg_id, f"🏫 <b>{len(results)} result(s):</b>", kb.inst_results_kb(results, tg_id))


@router.message(StateFilter(LoginStates.manual_url))
async def fsm_manual_url(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    raw = (message.text or "").strip()
    if not raw.startswith(("https://", "http://")):
        await _send(tg_id, "❌ Valid URL bhejiye (jaise <code>https://abcapi.classx.co.in</code>).")
        return
    try:
        parts = urlsplit(raw)
        if not parts.netloc or "." not in parts.netloc:
            raise ValueError()
    except Exception:
        await _send(tg_id, "❌ Valid URL nahi hai.")
        return
    found = ctx.registry.find_by_api(raw.rstrip("/"))
    tenant = found or Tenant(name=parts.netloc, api_base=raw.rstrip("/"))
    if not found:
        log.warning("custom tenant url=%s", parts.netloc)
    await state.update_data(tenant={"name": tenant.name, "api_base": tenant.api_base})
    await state.set_state(LoginStates.username)
    await _send(tg_id, msg.LOGIN_USERNAME, kb.login_cancel_kb())


@router.message(StateFilter(LoginStates.username))
async def fsm_username(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    username = (message.text or "").strip()[:128]
    if not username:
        return
    await state.update_data(username=username)
    await state.set_state(LoginStates.password)
    await _send(tg_id, msg.LOGIN_PASSWORD, kb.login_cancel_kb())


@router.message(StateFilter(LoginStates.password))
async def fsm_password(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    password = (message.text or "")[:256]
    data = await state.get_data()
    await state.clear()  # password message state turant clear

    if not ctx.limiter.allow(f"login:{tg_id}", *ctx.cfg.login_rate):
        await _send(tg_id, "⏳ Too many login attempts. Please try again in a few minutes.", kb.login_kb())
        return

    tenant_data = data.get("tenant")
    username = data.get("username", "")
    if not tenant_data or not username:
        await _send(tg_id, "❌ Login session expire ho gaya. Dobara start karein.", kb.login_kb())
        return
    tenant = Tenant(name=tenant_data["name"], api_base=tenant_data["api_base"])

    auth_msg = await _send_msg(tg_id, msg.LOGIN_AUTHENTICATING)
    result = await ctx.login_svc.attempt(tenant, username, password)
    password = ""  # discard

    if not result.ok:
        try:
            await ctx.bot.delete_message(tg_id, auth_msg.message_id)
        except TelegramAPIError:
            pass
        reason = result.error.message if result.error else "Please check your ID/password."
        await _send(tg_id, f"❌ <b>Login failed.</b>\n\n{reason}", kb.login_retry_kb())
        return

    session = result.session
    # tenant/session ko store karo (password kabhi nahi)
    ctx.sessions.save(tg_id, session, username)
    ctx.db.remember_tenant(tg_id, session.tenant_id, session.tenant_name)
    try:
        courses = await ctx.courses.list_courses(session, tg_id)
        ctx.db.save_courses(tg_id, session.tenant_id,
                            [{"course_id": c.course_id, "title": c.title, "meta": c.meta} for c in courses])
    except AppError:
        courses = []
    try:
        await ctx.bot.delete_message(tg_id, auth_msg.message_id)
    except TelegramAPIError:
        pass
    await _send(tg_id, msg.login_success(session.name or username, session.tenant_name, len(courses)))
    await _send(tg_id, msg.MENU, kb.main_menu_kb())


async def _send_msg(chat_id: int, text: str, markup=None) -> Message:
    return await ctx.bot.send_message(
        chat_id, text, parse_mode=ParseMode.HTML, reply_markup=markup
    )


# ================================================================= callbacks

@router.callback_query(F.data == "m:home")
async def cb_home(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    session = ctx.sessions.get(tg_id)
    if not session:
        await _edit(cb, msg.WELCOME, kb.login_kb())
        return
    await _edit(cb, msg.MENU, kb.main_menu_kb())
    await _answer(cb)


@router.callback_query(F.data == "m:courses")
async def cb_courses(cb: CallbackQuery) -> None:
    await _show_courses(cb, 0)


@router.callback_query(F.data.startswith("courses:p:"))
async def cb_courses_page(cb: CallbackQuery) -> None:
    parts = _data(cb)
    await _show_courses(cb, int(parts[2]))


async def _show_courses(cb: CallbackQuery, page: int) -> None:
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    if not courses:
        await _edit(cb, "📭 Aapke paas koi course available nahi hai.")
        return
    markup, total = kb.courses_kb(courses, page)
    await _edit(cb, msg.COURSES_HEADER, markup)
    await _answer(cb)


@router.callback_query(F.data == "m:export")
async def cb_export_menu(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    if not courses:
        await _edit(cb, "📭 Koi course nahi mila.")
        return
    selected = ctx.selection(tg_id, "export_mc")
    mode_hint = "ek hi file me sab courses" if ctx.cfg.export_mode == "single" else "har course ki alag file"
    await _edit(cb, msg.EXPORT_MULTI.format(mode=ctx.cfg.export_mode, mode_hint=mode_hint),
                kb.export_multi_kb(courses, selected))
    await _answer(cb)


@router.callback_query(F.data == "m:jobs")
async def cb_jobs(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    jobs = ctx.jobs.history(tg_id)
    if not jobs:
        await _edit(cb, msg.JOBS_EMPTY)
        await _answer(cb)
        return
    markup, _ = kb.jobs_kb(jobs, 0)
    await _edit(cb, msg.JOBS_HEADER, markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("jobs:p:"))
async def cb_jobs_page(cb: CallbackQuery) -> None:
    parts = _data(cb)
    tg_id = cb.from_user.id
    jobs = ctx.jobs.history(tg_id)
    if not jobs:
        await _edit(cb, msg.JOBS_EMPTY)
        return
    markup, _ = kb.jobs_kb(jobs, int(parts[2]))
    await _edit(cb, msg.JOBS_HEADER, markup)
    await _answer(cb)


async def _show_jobs(tg_id: int, message: Message, page: int) -> None:
    jobs = ctx.jobs.history(tg_id)
    if not jobs:
        await _send(tg_id, msg.JOBS_EMPTY)
        return
    markup, _ = kb.jobs_kb(jobs, page)
    await _send(tg_id, msg.JOBS_HEADER, markup)


@router.callback_query(F.data == "m:account")
async def cb_account(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    row = ctx.db.get_user(tg_id)
    courses = await ctx.courses.list_courses(session, tg_id)
    await _edit(cb, msg.ACCOUNT.format(
        tg_id=tg_id,
        name=session.name or "User",
        tenant_name=session.tenant_name,
        username=(row or {}).get("username", "-"),
        expiry=msg.fmt_expiry(session.expiry),
        courses=len(courses),
    ), kb.main_menu_kb())
    await _answer(cb)


@router.callback_query(F.data == "m:logout")
async def cb_logout(cb: CallbackQuery) -> None:
    await _edit(cb, msg.LOGOUT_CONFIRM, kb.logout_kb())
    await _answer(cb)


@router.callback_query(F.data == "logout:yes")
async def cb_logout_yes(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    await ctx.sessions.logout(tg_id)
    ctx.courses.invalidate(tg_id)
    ctx.content.invalidate(tg_id)
    await _edit(cb, msg.LOGGED_OUT, kb.login_kb())
    await _answer(cb)


# ---------------------------------------------------------------- login

@router.callback_query(F.data == "login:start")
async def cb_login_start(cb: CallbackQuery, state: FSMContext) -> None:
    tg_id = cb.from_user.id
    await state.clear()
    await state.set_state(LoginStates.inst_search)
    await _edit(cb, msg.LOGIN_INSTITUTE, None)
    await _answer(cb)


@router.callback_query(F.data.startswith("inst:last:"))
async def cb_inst_last(cb: CallbackQuery, state: FSMContext) -> None:
    parts = _data(cb)
    tenant_id = parts[2]
    row = ctx.db.get_user(cb.from_user.id)
    name = (row or {}).get("tenant_name") or tenant_id
    await state.update_data(tenant={"name": name, "api_base": f"https://{tenant_id}"})
    await state.set_state(LoginStates.username)
    await _edit(cb, msg.LOGIN_USERNAME, kb.login_cancel_kb())
    await _answer(cb)


@router.callback_query(F.data.startswith("inst:pick:"))
async def cb_inst_pick(cb: CallbackQuery, state: FSMContext) -> None:
    tg_id = cb.from_user.id
    idx = int(_data(cb)[2])
    results = ctx.inst_search.get(tg_id, [])
    if not (0 <= idx < len(results)):
        await _answer(cb, "❌ Try again")
        return
    tenant = results[idx]
    await state.update_data(tenant={"name": tenant.name, "api_base": tenant.api_base})
    await state.set_state(LoginStates.username)
    await _edit(cb, f"🏫 <b>{tenant.name}</b>\n\n{msg.LOGIN_USERNAME}", kb.login_cancel_kb())
    await _answer(cb)


@router.callback_query(F.data == "inst:manual")
async def cb_inst_manual(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LoginStates.manual_url)
    await _edit(cb, msg.LOGIN_MANUAL_URL, kb.login_cancel_kb())
    await _answer(cb)


@router.callback_query(F.data == "auth:abort")
async def cb_auth_abort(cb: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _edit(cb, msg.WELCOME, kb.login_kb())
    await _answer(cb)


# ---------------------------------------------------------------- courses

@router.callback_query(F.data.startswith("course:open:"))
async def cb_course_open(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    course_idx = int(_data(cb)[2])
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    counts = tree.counts()
    await _edit(cb, msg.COURSE_DETAIL.format(
        title=course.title,
        videos=counts["videos"],
        pdfs=counts["pdfs"],
        chapters=counts["chapters"],
    ), kb.course_detail_kb(course_idx))
    await _answer(cb)


# ---------------------------------------------------------------- content

@router.callback_query(F.data.startswith("content:open:"))
async def cb_content_open(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    course_idx = int(_data(cb)[2])
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    markup, _ = kb.content_kb(course_idx, tree, 0)
    await _edit(cb, msg.CONTENT_HEADER.format(title=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("content:p:"))
async def cb_content_page(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    _, _, course_idx, page = _data(cb)
    course_idx, page = int(course_idx), int(page)
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    markup, _ = kb.content_kb(course_idx, tree, page)
    await _edit(cb, msg.CONTENT_HEADER.format(title=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("content:ch:"))
async def cb_content_chapter(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    _, _, course_idx, ch_idx, page = _data(cb)
    course_idx, ch_idx, page = int(course_idx), int(ch_idx), int(page)
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
        if not (0 <= ch_idx < len(tree.chapters)):
            raise AppError("not_found", "Chapter not found.")
        chapter = tree.chapters[ch_idx]
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    markup, _ = kb.chapter_items_kb(course_idx, ch_idx, chapter.items, page)
    await _edit(cb, f"📚 <b>{course.title}</b> — {chapter.title}", markup)
    await _answer(cb)


@router.callback_query(F.data == "chapter:noop")
async def cb_noop(cb: CallbackQuery) -> None:
    await _answer(cb, "👆 Item — export ya job me select kar sakte hain")


@router.callback_query(F.data == "m:content_pick")
async def cb_content_pick(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    markup, _ = kb.courses_kb(courses, action="content:open")
    await _edit(cb, "📋 <b>Content dekhne ke liye course choose karein:</b>", markup)
    await _answer(cb)


# ---------------------------------------------------------------- export

@router.callback_query(F.data.startswith("export:opt:"))
async def cb_export_opt(cb: CallbackQuery) -> None:
    course_idx = int(_data(cb)[2])
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    await _edit(cb, msg.EXPORT_OPTIONS.format(course=course.title), kb.export_options_kb(course_idx))
    await _answer(cb)


@router.callback_query(F.data.startswith("export:kind:"))
async def cb_export_kind(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx, kind = int(parts[2]), parts[3]
    tg_id = cb.from_user.id
    if not ctx.limiter.allow(f"export:{tg_id}", *ctx.cfg.export_rate):
        await _answer(cb, "⏳ Slow down! Thoda ruk kar try karein.")
        return
    await _edit(cb, msg.EXPORT_STARTED.format(course="..."), None)
    await _answer(cb)
    await _run_export(tg_id, cb, course_idx, kind, None)


@router.callback_query(F.data.startswith("export:ch:"))
async def cb_export_chapters(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx, page = int(parts[2]), int(parts[3]) if len(parts) > 3 else 0
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, f"export_ch:{course_idx}")
    markup, _ = kb.export_chapters_kb(course_idx, tree, selected, page)
    await _edit(cb, msg.EXPORT_SELECT_CHAPTERS.format(course=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("export:tgl:"))
async def cb_export_toggle(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx, ch_idx = int(parts[2]), int(parts[3])
    tg_id = cb.from_user.id
    selected = ctx.selection(tg_id, f"export_ch:{course_idx}")
    if ch_idx in selected:
        selected.discard(ch_idx)
    else:
        selected.add(ch_idx)
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    markup, _ = kb.export_chapters_kb(course_idx, tree, selected, 0)
    await _edit(cb, msg.EXPORT_SELECT_CHAPTERS.format(course=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("export:all:"))
async def cb_export_all(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx = int(parts[2])
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, f"export_ch:{course_idx}")
    selected.update(range(len(tree.chapters)))
    markup, _ = kb.export_chapters_kb(course_idx, tree, selected, 0)
    await _edit(cb, msg.EXPORT_SELECT_CHAPTERS.format(course=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("export:go:"))
async def cb_export_go(cb: CallbackQuery) -> None:
    course_idx = int(_data(cb)[2])
    tg_id = cb.from_user.id
    selected = ctx.selection(tg_id, f"export_ch:{course_idx}")
    if not selected:
        await _answer(cb, "📂 Pehle kam se kam ek chapter select karein!")
        return
    if not ctx.limiter.allow(f"export:{tg_id}", *ctx.cfg.export_rate):
        await _answer(cb, "⏳ Slow down! Thoda ruk kar try karein.")
        return
    await _edit(cb, msg.EXPORT_STARTED.format(course="..."), None)
    await _answer(cb)
    await _run_export(tg_id, cb, course_idx, "complete", set(selected))


@router.callback_query(F.data.startswith("export:mc:"))
async def cb_export_mc_toggle(cb: CallbackQuery) -> None:
    course_idx = int(_data(cb)[2])
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, "export_mc")
    if course_idx in selected:
        selected.discard(course_idx)
    else:
        selected.add(course_idx)
    await _edit(cb, msg.EXPORT_MULTI.format(mode=ctx.cfg.export_mode, mode_hint=""),
                kb.export_multi_kb(courses, selected))
    await _answer(cb)


@router.callback_query(F.data == "export:all_mc")
async def cb_export_mc_all(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, "export_mc")
    selected.update(range(len(courses)))
    await _edit(cb, msg.EXPORT_MULTI.format(mode=ctx.cfg.export_mode, mode_hint=""),
                kb.export_multi_kb(courses, selected))
    await _answer(cb)


@router.callback_query(F.data == "export:go_mc")
async def cb_export_go_mc(cb: CallbackQuery) -> None:
    tg_id = cb.from_user.id
    selected = ctx.selection(tg_id, "export_mc")
    if not selected:
        await _answer(cb, "📄 Pehle kam se kam ek course select karein!")
        return
    if not ctx.limiter.allow(f"export:{tg_id}", *ctx.cfg.export_rate):
        await _answer(cb, "⏳ Slow down! Thoda ruk kar try karein.")
        return
    await _edit(cb, msg.EXPORT_STARTED.format(course="multiple courses"), None)
    await _answer(cb)
    await _run_export_multi(tg_id, cb, sorted(selected))


async def _run_export(tg_id: int, cb: CallbackQuery, course_idx: int, kind: str, chapter_idx: set[int] | None) -> None:
    import time as _time

    export_id = None
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        export_id = f"EXP-{int(_time.time() * 1000) % 100000:05d}"
        files = await ctx.exports.generate(
            session, tg_id, [course], kind=kind, chapter_idx=chapter_idx, export_id=export_id
        )
        await _edit(cb, msg.EXPORT_READY, None)
        await _deliver_documents(tg_id, files)
    except AppError as e:
        await _edit(cb, msg.EXPORT_ERROR.format(reason=safe_error_message(e)))
    except Exception as e:
        ctx.stats["api_errors"] += 1
        log.error("export failed err=%s", e.__class__.__name__)
        await _edit(cb, msg.EXPORT_ERROR.format(reason="Something went wrong."))
    finally:
        if export_id:
            try:
                ctx.exports.delete_export(export_id)
            except Exception:
                pass


async def _deliver_documents(tg_id: int, files) -> None:
    """Files delivery: channel set hai to channel par, warna DM.
    DM me confirmation chalti hai."""
    target = ctx.cfg.upload_channel_id or tg_id
    for f in files:
        try:
            await ctx.bot.send_document(target, FSInputFile(f))
        except TelegramAPIError:
            ctx.stats["tg_errors"] += 1
            await _send(tg_id, f"❌ <code>{f.name}</code> upload fail ho gaya.")
            continue
        if ctx.cfg.upload_channel_id:
            await _send(tg_id, f"📄 <code>{f.name}</code> channel par bhej diya ✅")


async def _run_export_multi(tg_id: int, cb: CallbackQuery, course_idxs: list[int]) -> None:
    import time as _time

    export_id = None
    try:
        session = _require_session(tg_id)
        courses = await ctx.courses.list_courses(session, tg_id)
        selected_courses = [c for i, c in enumerate(courses) if i in course_idxs]
        if not selected_courses:
            await _edit(cb, msg.EXPORT_ERROR.format(reason="No courses selected."))
            return
        export_id = f"EXP-{int(_time.time() * 1000) % 100000:05d}"
        files = await ctx.exports.generate(
            session, tg_id, selected_courses, kind="complete", chapter_idx=None, export_id=export_id
        )
        await _edit(cb, msg.EXPORT_READY, None)
        await _deliver_documents(tg_id, files)
    except AppError as e:
        await _edit(cb, msg.EXPORT_ERROR.format(reason=safe_error_message(e)))
    except Exception as e:
        ctx.stats["api_errors"] += 1
        log.error("multi export failed err=%s", e.__class__.__name__)
        await _edit(cb, msg.EXPORT_ERROR.format(reason="Something went wrong."))
    finally:
        if export_id:
            try:
                ctx.exports.delete_export(export_id)
            except Exception:
                pass


# ---------------------------------------------------------------- jobs

@router.callback_query(F.data.startswith("job:scope:"))
async def cb_job_scope(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx = int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, f"job_ch:{course_idx}")
    if not selected:
        selected.update(range(len(tree.chapters)))
    markup, _ = kb.job_scope_kb(course_idx, tree, selected, page)
    await _edit(cb, msg.JOB_SCOPE.format(course=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("job:tgl:"))
async def cb_job_toggle(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx, ch_idx = int(parts[2]), int(parts[3])
    tg_id = cb.from_user.id
    selected = ctx.selection(tg_id, f"job_ch:{course_idx}")
    if ch_idx in selected:
        selected.discard(ch_idx)
    else:
        selected.add(ch_idx)
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    markup, _ = kb.job_scope_kb(course_idx, tree, selected, 0)
    await _edit(cb, msg.JOB_SCOPE.format(course=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("job:all:"))
async def cb_job_all(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx = int(parts[2])
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, f"job_ch:{course_idx}")
    selected.update(range(len(tree.chapters)))
    markup, _ = kb.job_scope_kb(course_idx, tree, selected, 0)
    await _edit(cb, msg.JOB_SCOPE.format(course=course.title), markup)
    await _answer(cb)


@router.callback_query(F.data.startswith("job:mk:"))
async def cb_job_make(cb: CallbackQuery) -> None:
    parts = _data(cb)
    course_idx = int(parts[2])
    tg_id = cb.from_user.id
    try:
        session = _require_session(tg_id)
        course = await ctx.courses.get_course(session, tg_id, course_idx)
        tree = await ctx.content.get_tree(session, tg_id, course)
    except AppError as e:
        await _edit(cb, e.message, kb.login_kb() if e.code == "unauthorized" else None)
        return
    selected = ctx.selection(tg_id, f"job_ch:{course_idx}")
    if not selected:
        selected.update(range(len(tree.chapters)))
    # items snapshot (authorized content hi)
    items = []
    for idx, ch in enumerate(tree.chapters):
        if idx in selected:
            items.extend(ch.items)
    media_items = [it for it in items if it.reference and it.type in ("video", "pdf")]
    if not media_items:
        await _answer(cb, "❌ Is selection me koi downloadable media nahi hai.")
        return

    busy = ctx.jobs.global_full()
    try:
        job = await ctx.jobs.create_job(session, tg_id, course, media_items,
                                        progress_msg_id=cb.message.message_id)
    except AppError as e:
        await _answer(cb, safe_error_message(e))
        return
    if busy:
        await _answer(cb, msg.BUSY)
    await _edit(cb, msg.JOB_CREATED.format(
        job_id=job["job_id"], course=course.title, total=job["total"]
    ), kb.job_kb(job["job_id"]))
    log.info("job created via bot %s user=%s items=%d", job["job_id"], tg_id, job["total"])


@router.callback_query(F.data.startswith("job:status:"))
async def cb_job_status(cb: CallbackQuery) -> None:
    parts = _data(cb)
    job_id = parts[2].upper()
    tg_id = cb.from_user.id
    try:
        job = ctx.jobs.get_job(job_id, tg_id)
        items = ctx.jobs.get_job_items(job_id, tg_id)
    except AppError as e:
        await _edit(cb, e.message)
        return
    failed = [it for it in items if it["status"] == "failed"]
    lines = [ctx.jobs.progress_text(job)]
    if failed:
        lines.append("\n❌ <b>Failed items:</b>")
        for it in failed[:5]:
            lines.append(f"• {it['chapter']} — {it['title']}")
    active = job["status"] in ("queued", "processing")
    await _edit(cb, "\n".join(lines), kb.job_detail_kb(job_id, active))
    await _answer(cb)


@router.callback_query(F.data.startswith("job:cancel:"))
async def cb_job_cancel(cb: CallbackQuery) -> None:
    parts = _data(cb)
    job_id = parts[2].upper()
    tg_id = cb.from_user.id
    try:
        job = ctx.jobs.get_job(job_id, tg_id)
    except AppError as e:
        await _edit(cb, e.message)
        return
    await _edit(cb, msg.JOB_CANCEL_CONFIRM.format(
        job_id=job["job_id"], course=job["course_title"], status=job["status"]
    ), kb.cancel_confirm_kb(job_id))
    await _answer(cb)


@router.callback_query(F.data.startswith("job:cc:"))
async def cb_job_cancel_yes(cb: CallbackQuery) -> None:
    parts = _data(cb)
    job_id = parts[2].upper()
    tg_id = cb.from_user.id
    try:
        job = ctx.jobs.cancel(job_id, tg_id)
    except AppError as e:
        await _edit(cb, e.message)
        return
    await _edit(cb, msg.JOB_CANCELLED.format(job_id=job_id), kb.job_detail_kb(job_id, False))
    await _answer(cb, "✅ Job cancelled.")


@router.callback_query(F.data.startswith("job:retry:"))
async def cb_job_retry(cb: CallbackQuery) -> None:
    parts = _data(cb)
    job_id, item_id = parts[2].upper(), int(parts[3])
    tg_id = cb.from_user.id
    try:
        job = ctx.jobs.retry_item(job_id, tg_id, item_id)
    except AppError as e:
        await _answer(cb, safe_error_message(e))
        return
    await _answer(cb, "🔄 Item queue me wapas daal diya gaya.")
    await _edit(cb, ctx.jobs.progress_text(job), kb.job_kb(job_id))


@router.callback_query(F.data.startswith("job:skip:"))
async def cb_job_skip(cb: CallbackQuery) -> None:
    parts = _data(cb)
    job_id, item_id = parts[2].upper(), int(parts[3])
    tg_id = cb.from_user.id
    try:
        job = ctx.jobs.skip_item(job_id, tg_id, item_id)
    except AppError as e:
        await _answer(cb, safe_error_message(e))
        return
    await _answer(cb, "⏭️ Item skip kar diya gaya.")


# ---------------------------------------------------------------- fallback

@router.callback_query()
async def cb_unknown(cb: CallbackQuery) -> None:
    await _answer(cb, "❓ Unknown action")


@router.message()
async def msg_unknown(message: Message) -> None:
    tg_id = message.from_user.id
    session = ctx.sessions.get(tg_id)
    if session:
        await _send(tg_id, "❓ Samajh nahi aaya. Menu use karein 👇", kb.main_menu_kb())
    else:
        await _send(tg_id, msg.WELCOME, kb.login_kb())
