"""
TelegramGateway — worker/export services ka Telegram se ek hi entry point.

Real bot (aiogram) ya FakeBot (tests) dono is interface ko implement karte
hain, isliye worker/export bina real Telegram ke test ho sakta hai.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.types import FSInputFile

from utils.logger import get_logger

log = get_logger("gateway")


@dataclass
class SendResult:
    ok: bool
    message_id: int | None = None
    error: str | None = None


class BaseGateway(ABC):
    @abstractmethod
    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> SendResult: ...

    @abstractmethod
    async def edit_message(self, chat_id: int, message_id: int, text: str, reply_markup=None) -> SendResult: ...

    @abstractmethod
    async def send_document(self, chat_id: int, file_path: str, filename: str | None = None, caption: str | None = None) -> SendResult: ...

    @abstractmethod
    async def delete_message(self, chat_id: int, message_id: int) -> SendResult: ...


class AiogramGateway(BaseGateway):
    """Real implementation using aiogram Bot."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_message(self, chat_id, text, reply_markup=None) -> SendResult:
        try:
            msg = await self.bot.send_message(
                chat_id, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup
            )
            return SendResult(ok=True, message_id=msg.message_id)
        except TelegramRetryAfter as e:
            return SendResult(ok=False, error=f"telegram_rate:{e.retry_after}")
        except TelegramAPIError as e:
            log.warning("send_message failed chat=%s err=%s", chat_id, e.__class__.__name__)
            return SendResult(ok=False, error="telegram_error")

    async def edit_message(self, chat_id, message_id, text, reply_markup=None) -> SendResult:
        try:
            msg = await self.bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup,
            )
            return SendResult(ok=True, message_id=msg.message_id)
        except TelegramAPIError as e:
            log.debug("edit_message failed msg=%s err=%s", message_id, e.__class__.__name__)
            return SendResult(ok=False, error="telegram_error")

    async def send_document(self, chat_id, file_path, filename=None, caption=None) -> SendResult:
        try:
            doc = FSInputFile(file_path, filename=filename or Path(file_path).name)
            msg = await self.bot.send_document(
                chat_id,
                doc,
                caption=(caption or "")[:1000] or None,
                parse_mode=ParseMode.HTML,
            )
            return SendResult(ok=True, message_id=msg.message_id)
        except TelegramRetryAfter as e:
            return SendResult(ok=False, error=f"telegram_rate:{e.retry_after}")
        except TelegramAPIError as e:
            log.warning(
                "send_document failed chat=%s file=%s err=%s",
                chat_id, Path(file_path).name, e.__class__.__name__,
            )
            return SendResult(ok=False, error="telegram_error")

    async def delete_message(self, chat_id, message_id) -> SendResult:
        try:
            await self.bot.delete_message(chat_id, message_id)
            return SendResult(ok=True)
        except TelegramAPIError:
            return SendResult(ok=False, error="telegram_error")
