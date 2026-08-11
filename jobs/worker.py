"""
Sequential worker — PRD sections 15-18.

- Har worker ek job ko item-by-item process karta hai (low RAM/disk).
- Retry engine: retryable errors → MAX_RETRIES attempts with backoff.
- Progress message edit hoti hai (nayi message nahi).
- Cancel: queued items cancel; processing item safely stop; files delete.
- Har item: download → upload → verify → delete.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from config import Config
from jobs.manager import JobManager
from jobs.queue import JobQueue
from platforms.models import ContentItem, SessionData
from services.media import MediaService
from storage.database import Database
from utils.gateway import BaseGateway
from utils.logger import get_logger
from utils.security import AppError, RETRYABLE_ERRORS, safe_error_message

log = get_logger("worker")

_PROGRESS_EDIT_INTERVAL = 2.0

_ERROR_LABELS = {
    "unauthorized": "Session invalid. Login again.",
    "forbidden": "Content unavailable for this account.",
    "not_found": "Content not found.",
    "network": "Temporary network error.",
    "timeout": "Timeout.",
    "http_5xx": "Temporary server error.",
    "http_error": "Request failed.",
    "unsupported_media": "Media cannot be processed through the available authorized method.",
    "drm_protected": "Media is DRM-protected — authorized method unavailable.",
    "file_too_large": "File too large for Telegram delivery.",
    "processing_error": "Processing failed.",
    "telegram_error": "Telegram upload failed.",
    "invalid_input": "Invalid request.",
    "limit": "Rate limit reached.",
    "unknown": "Something went wrong.",
}


class Worker:
    def __init__(self, cfg: Config, db: Database, queue: JobQueue,
                 manager: JobManager, media: MediaService, gateway: BaseGateway,
                 sessions=None):
        self.cfg = cfg
        self.db = db
        self.queue = queue
        self.manager = manager
        self.media = media
        self.gateway = gateway
        self.sessions = sessions  # SessionManager (optional in tests)
        self._tasks: list[asyncio.Task] = []
        self._stopping = False

    def start(self) -> None:
        """Worker pool — size = MAX_ACTIVE_JOBS (global limit)."""
        for _ in range(max(1, self.cfg.max_active_jobs)):
            self._tasks.append(asyncio.create_task(self._run_loop(), name="appx-worker"))

    async def stop(self) -> None:
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    # ------------------------------------------------------------ loop

    async def _run_loop(self) -> None:
        while not self._stopping:
            job_id = await self.queue.get()
            try:
                await self._process_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("worker crash job=%s err=%s", job_id, e.__class__.__name__)
            finally:
                self.queue.task_done()

    async def _process_job(self, job_id: str) -> None:
        job = self.db.get_job(job_id)
        if not job:
            return
        if job["status"] != "queued":
            return  # cancelled/already done
        self.db.update_job(job_id, status="processing")

        # authorized session — worker ko bhi user ka encrypted session milta hai
        # (password/token kabhi plaintext log/store nahi hote)
        session = self.sessions.get(job["telegram_user_id"]) if self.sessions else None
        if not session:
            queued = self.db.get_job_items(job_id, status="queued")
            for item in queued:
                self.db.update_item(item["item_id"], status="failed",
                                    error_code="unauthorized", error_message="Session expired.")
            self.db.update_job(job_id, failed=len(queued), status="failed")
            await self.gateway.send_message(
                job["telegram_user_id"],
                "⚠️ <b>Session expired.</b>\nPlease login again.\n\n"
                f"Job <b>{job_id}</b> ko process nahi kiya ja saka.",
            )
            self._cleanup_job_dir(job_id)
            return

        items = self.db.get_job_items(job_id, status="queued")
        progress_msg_id = job.get("progress_msg_id")
        last_edit = 0.0

        async def update_progress(force: bool = False) -> None:
            nonlocal progress_msg_id, last_edit
            now = asyncio.get_event_loop().time()
            if not force and now - last_edit < _PROGRESS_EDIT_INTERVAL:
                return
            last_edit = now
            job = self.db.get_job(job_id)
            text = self.manager.progress_text(job)
            if progress_msg_id:
                res = await self.gateway.edit_message(job["telegram_user_id"], progress_msg_id, text)
                if not res.ok:
                    progress_msg_id = None
            if not progress_msg_id:
                res = await self.gateway.send_message(job["telegram_user_id"], text)
                if res.ok:
                    progress_msg_id = res.message_id
                    self.db.update_job(job_id, progress_msg_id=progress_msg_id)

        await update_progress(force=True)

        for item in items:
            job = self.db.get_job(job_id)
            if job["status"] == "cancelled":
                self.db.update_item(item["item_id"], status="cancelled",
                                    error_code="cancelled", error_message="Job cancelled.")
                continue

            self.db.update_item(item["item_id"], status="processing")
            self.db.update_job(job_id, current_item=f"{item['chapter']} - {item['title']}")
            await update_progress()

            ok, error = await self._process_one(job, item)

            if job["status"] == "cancelled":
                self.db.update_item(item["item_id"], status="cancelled",
                                    error_code="cancelled", error_message="Job cancelled.")
                continue

            if ok:
                self.db.update_item(item["item_id"], status="completed")
                self.db.update_job(job_id, completed=self.db.get_job(job_id)["completed"] + 1,
                                   current_item="")
                self._cleanup_item_files(job_id)
            else:
                self.db.update_item(item["item_id"], status="failed",
                                    error_code=error.code, error_message=error.message)
                self.db.update_job(job_id, failed=self.db.get_job(job_id)["failed"] + 1,
                                   current_item="")
                self._cleanup_item_files(job_id)
                await self._notify_failed(job["telegram_user_id"], job_id, item, error)
            await update_progress(force=True)

        # final state
        job = self.db.get_job(job_id)
        if job["status"] == "cancelled":
            await self._finalize(job, "🚫 <b>Job cancelled.</b>")
        elif job["failed"] and job["completed"] + job["failed"] == job["total"]:
            await self._finalize(job, f"⚠️ <b>Job {job_id} finished with {job['failed']} failed item(s).</b>")
        else:
            await self._finalize(job, f"✅ <b>Job {job_id} completed.</b> {job['completed']}/{job['total']} items delivered.")

    async def _process_one(self, job: dict, item: dict) -> tuple[bool, AppError]:
        """Download → upload → delete. Retries retryable errors."""
        attempts = 0
        max_attempts = max(1, self.cfg.max_retries)
        last_error = AppError("unknown", "Something went wrong.")

        while attempts < max_attempts:
            job = self.db.get_job(job["job_id"])
            if job["status"] == "cancelled":
                return False, AppError("cancelled", "Job cancelled.")
            attempts += 1
            self.db.update_item(item["item_id"], retry_count=attempts)
            file_path: Path | None = None
            try:
                content_item = ContentItem(
                    content_id=item["content_id"], title=item["title"],
                    type=item["type"], chapter=item["chapter"], reference=item["reference"],
                )
                file_path = await self.media.process(
                    self._session_for(job), content_item, job["job_id"], item["item_id"]
                )
            except AppError as e:
                last_error = e
                if e.code == "cancelled":
                    return False, e
                if e.code not in RETRYABLE_ERRORS:
                    return False, e
                log.warning("item retryable err job=%s item=%s code=%s attempt=%d",
                            job["job_id"], item["item_id"], e.code, attempts)
            except Exception as e:
                log.error("item crash job=%s item=%s err=%s",
                          job["job_id"], item["item_id"], e.__class__.__name__)
                last_error = AppError("processing_error", "Processing failed.")
                return False, last_error  # unexpected — non-retryable, fail fast

            if file_path and file_path.exists():
                res = await self.gateway.send_document(
                    job["telegram_user_id"], str(file_path),
                    filename=file_path.name,
                    caption=f"📚 {job['course_title']}\n📂 {item['chapter']}\n🎯 {item['title']}",
                )
                if res.ok:
                    file_path.unlink(missing_ok=True)
                    log.info("item delivered job=%s item=%s", job["job_id"], item["item_id"])
                    return True, AppError("", "")
                last_error = AppError("telegram_error", "Telegram upload failed.")
                if res.error and res.error.startswith("telegram_rate:"):
                    await asyncio.sleep(min(30, int(res.error.split(":")[1])))
                else:
                    log.warning("upload failed job=%s item=%s err=%s",
                                job["job_id"], item["item_id"], res.error)
                if attempts < max_attempts:
                    await asyncio.sleep(self._backoff(attempts))
                continue

            if attempts < max_attempts and last_error.code in RETRYABLE_ERRORS:
                await asyncio.sleep(self._backoff(attempts))
            elif attempts >= max_attempts:
                break
        return False, last_error

    def _session_for(self, job: dict) -> SessionData:
        """Media download ke liye job owner ka authorized session (already
        verified in _process_job). Live mode me token sirf same-host CDN
        requests me bheja jata hai (media service me check hota hai)."""
        if self.sessions:
            return self.sessions.get(job["telegram_user_id"]) or SessionData(token="", tenant_id=job.get("tenant_id", ""))
        return SessionData(token="", tenant_id=job.get("tenant_id", ""))

    def _backoff(self, attempt: int) -> int:
        backoff = getattr(self.cfg, "retry_backoff", [5, 15, 30]) or [5]
        return backoff[min(attempt - 1, len(backoff) - 1)]

    async def _notify_failed(self, chat_id: int, job_id: str, item: dict, error: AppError) -> None:
        from bot.keyboards import failed_item_kb

        label = _ERROR_LABELS.get(error.code, error.message)
        text = (
            f"❌ <b>Item failed</b>\n"
            f"Job: {job_id}\n"
            f"📂 {item['chapter']} — {item['title']}\n"
            f"Reason: {label}"
        )
        await self.gateway.send_message(chat_id, text, reply_markup=failed_item_kb(job_id, item["item_id"]))

    async def _finalize(self, job: dict, headline: str) -> None:
        job_id = job["job_id"]
        # status: "completed" = job apne end tak chala (⚠️ = failed items ke saath),
        # "cancelled" = user ne cancel kiya. "failed" reserved for never-ran jobs.
        status = "cancelled" if "cancelled" in headline else "completed"
        self.db.update_job(job_id, status=status, current_item="")
        job = self.db.get_job(job_id)
        final = headline + "\n\n" + self.manager.progress_text(job)
        if job.get("progress_msg_id"):
            res = await self.gateway.edit_message(job["telegram_user_id"], job["progress_msg_id"], final)
            if not res.ok:
                await self.gateway.send_message(job["telegram_user_id"], final)
        else:
            await self.gateway.send_message(job["telegram_user_id"], final)
        self._cleanup_job_dir(job_id)
        log.info("job finalize %s status=%s", job_id, status)

    def _cleanup_item_files(self, job_id: str) -> None:
        path = Path(self.media.job_dir) / job_id
        if path.exists():
            for f in path.iterdir():
                if f.is_file() and f.name != ".keep":
                    try:
                        f.unlink()
                    except OSError:
                        pass

    def _cleanup_job_dir(self, job_id: str) -> None:
        shutil.rmtree(Path(self.media.job_dir) / job_id, ignore_errors=True)
