"""Handler smoke test — aiogram MockedBot se bot UI flow check (bina network).

    .venv/bin/python tests/smoke_bot.py

Login FSM → menu → courses → course → export options → logout tak.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_TMP = tempfile.mkdtemp(prefix="appx-smoke-")
os.environ.update({
    "PLATFORM_MODE": "mock",
    "DATABASE_PATH": os.path.join(_TMP, "smoke.db"),
    "EXPORT_DIR": os.path.join(_TMP, "exports"),
    "JOB_DIR": os.path.join(_TMP, "jobs"),
    "LOG_LEVEL": "WARNING",
    "RETRY_BACKOFF_SEC": "0,0,0",
})

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.client.telegram import TelegramAPIServer  # noqa: E402
from aiogram.fsm.storage.memory import MemoryStorage  # noqa: E402
from aiogram.types import CallbackQuery, Chat, Document, Message, Update, User  # noqa: E402

from bot import handlers  # noqa: E402
from config import load_config  # noqa: E402
from context import ctx  # noqa: E402
from main import _build_context  # noqa: E402

TG = 555555
CHAT = Chat(id=TG, type="private")
USER = User(id=TG, is_bot=False, first_name="Smoke")


class FakeSession(BaseSession):
    """Records all API calls; real network nahi lagta."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list = []

    async def make_request(self, bot, method, timeout=None):
        from aiogram.methods import (  # noqa: E402
            AnswerCallbackQuery, DeleteMessage, EditMessageText, GetMe, SendDocument, SendMessage,
        )

        self.requests.append(method)
        name = type(method).__name__
        if name == "GetMe":
            return User(id=1, is_bot=True, first_name="AppxBot", username="appxbot")
        if name == "SendMessage":
            return Message(
                message_id=len(self.requests), date=1700000000,
                chat=method.chat_id if isinstance(method.chat_id, Chat) else CHAT,
                from_user=USER, text=method.text,
            )
        if name == "EditMessageText":
            return Message(
                message_id=method.message_id or 1, date=1700000000,
                chat=method.chat_id if isinstance(method.chat_id, Chat) else CHAT,
                from_user=USER, text=method.text,
            )
        if name == "SendDocument":
            return Message(
                message_id=len(self.requests), date=1700000000,
                chat=method.chat_id if isinstance(method.chat_id, Chat) else CHAT,
                from_user=USER, document=Document(file_id="x", file_unique_id="y"),
            )
        if name in ("DeleteMessage", "AnswerCallbackQuery"):
            return True
        return True

    async def stream_content(self, url, timeout=None, chunk_size=65536):
        yield b""

    async def close(self) -> None:
        pass


def msg_update(text: str, message_id: int = 1) -> Update:
    return Update(
        update_id=message_id,
        message=Message(
            message_id=message_id, date=1700000000, chat=CHAT, from_user=USER, text=text,
        ),
    )


def cb_update(data: str, message_id: int = 1, text: str = "menu") -> Update:
    return Update(
        update_id=1000 + message_id,
        callback_query=CallbackQuery(
            id=f"cb-{message_id}", from_user=USER, chat_instance="ci",
            data=data,
            message=Message(
                message_id=message_id, date=1700000000, chat=CHAT,
                from_user=USER, text=text,
            ),
        ),
    )


async def main() -> int:
    cfg = load_config()
    session = FakeSession()
    bot = Bot(token="123456:TESTTOKEN", session=session, server=TelegramAPIServer.from_base("https://api.telegram.org"))
    _build_context(cfg, bot=bot)
    await ctx.client.start()
    await ctx.media.start()
    ctx.worker.start()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    steps = [
        ("/start", "welcome + login button"),
        ("login flow: institute search", None),
        ("/login", "institute prompt"),
        ("Demo Institute", "institute results"),
        (None, "pick demo institute (callback inst:pick:0)"),
        ("demo", "username prompt"),
        ("demo123", "login success + menu"),
        (None, "courses list (callback m:courses)"),
        (None, "course detail (callback course:open:0)"),
        (None, "export options (callback export:opt:0)"),
        (None, "logout confirm (callback m:logout)"),
        (None, "logout yes (callback logout:yes)"),
    ]

    ok = True
    mid = 1
    # /start
    await dp.feed_update(bot, msg_update("/start", mid))
    # /login
    await dp.feed_update(bot, msg_update("/login", mid + 1))
    # institute search text
    await dp.feed_update(bot, msg_update("Demo Institute", mid + 2))
    # pick institute
    await dp.feed_update(bot, cb_update("inst:pick:0", mid + 3))
    # username
    await dp.feed_update(bot, msg_update("demo", mid + 4))
    # password
    await dp.feed_update(bot, msg_update("demo123", mid + 5))
    # courses
    await dp.feed_update(bot, cb_update("m:courses", mid + 6))
    # course open
    await dp.feed_update(bot, cb_update("course:open:0", mid + 7))
    # content view
    await dp.feed_update(bot, cb_update("content:open:0", mid + 8))
    # chapter items
    await dp.feed_update(bot, cb_update("content:ch:0:0:0", mid + 9))
    # export options
    await dp.feed_update(bot, cb_update("export:opt:0", mid + 10))
    # export complete (mock: generates + sends document)
    await dp.feed_update(bot, cb_update("export:kind:0:complete", mid + 11))
    await asyncio.sleep(0.5)
    # create media job (select all chapters, create)
    await dp.feed_update(bot, cb_update("job:scope:0", mid + 12))
    await dp.feed_update(bot, cb_update("job:mk:0", mid + 13))
    await asyncio.sleep(2.0)  # worker ko job process karne do
    # job status
    await dp.feed_update(bot, cb_update("m:jobs", mid + 14))
    # logout
    await dp.feed_update(bot, cb_update("m:logout", mid + 15))
    await dp.feed_update(bot, cb_update("logout:yes", mid + 16))

    texts = []
    for r in bot.session.requests:
        t = getattr(r, "text", None) or ""
        texts.append(t)
        kb = getattr(r, "reply_markup", None)
        if kb and kb.inline_keyboard:
            for row in kb.inline_keyboard:
                for btn in row:
                    texts.append(btn.text)
    joined = "\n".join(texts)

    checks = {
        "welcome": "Welcome to APPX Course Bot" in joined,
        "login_success": "Login Successful" in joined,
        "menu": "My Courses" in joined,
        "courses_list": "YOUR COURSES" in joined,
        "course_detail": "Physics" in joined and "Videos:" in joined,
        "content": "Chapter 01" in joined,
        "export_ready": "TXT file is ready" in joined,
        "job_created": "Job Created" in joined,
        "logged_out": "Logged out successfully" in joined,
    }
    for name, passed in checks.items():
        print(f"  {'✅' if passed else '❌'} {name}")
        ok = ok and passed

    # job should have completed in background
    job = ctx.jobs.history(TG)
    if job:
        j = job[0]
        print(f"  {'✅' if j['status'] == 'completed' and j['completed'] == j['total'] else '❌'} job completed: {j['status']} {j['completed']}/{j['total']}")
        ok = ok and (j["status"] == "completed" and j["completed"] == j["total"])

    await ctx.worker.stop()
    await ctx.client.stop()
    await ctx.media.stop()
    ctx.db.close()
    print(f"\nSMOKE RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(main()) == 0 else 1)
