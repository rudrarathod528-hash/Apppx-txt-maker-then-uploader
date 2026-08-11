"""
Job manager — PRD sections 14, 17, 23, 27-28.

Job creation, ownership validation, cancel, retry/skip, history, stats.
Har method telegram_user_id se ownership verify karta hai.
"""
from __future__ import annotations

from typing import Any

from config import Config
from jobs.queue import JobQueue
from platforms.models import ContentItem, ContentTree, Course, SessionData
from services.content import ContentService
from services.courses import CourseService
from storage.database import Database
from utils.helpers import now_ts
from utils.logger import get_logger
from utils.security import AppError, random_job_id

log = get_logger("jobs")

ACTIVE_STATUSES = ("queued", "processing")


class JobManager:
    def __init__(self, cfg: Config, db: Database, queue: JobQueue,
                 courses_svc: CourseService, content_svc: ContentService):
        self.cfg = cfg
        self.db = db
        self.queue = queue
        self.courses_svc = courses_svc
        self.content_svc = content_svc

    # ------------------------------------------------------------ creation

    async def create_job(
        self,
        session: SessionData,
        tg_id: int,
        course: Course,
        items: list[ContentItem],
        progress_msg_id: int | None = None,
    ) -> dict:
        if not items:
            raise AppError("invalid_input", "No items selected for the job.")

        active = [j for j in self.db.list_jobs(tg_id)
                  if j["status"] in ACTIVE_STATUSES]
        if len(active) >= self.cfg.max_jobs_per_user:
            raise AppError(
                "limit",
                f"Already {self.cfg.max_jobs_per_user} active job(s). "
                "Pehle koi job complete/cancel karein.",
            )

        job_id = random_job_id()
        while self.db.get_job(job_id):
            job_id = random_job_id()

        job = {
            "job_id": job_id,
            "telegram_user_id": tg_id,
            "course_id": course.course_id,
            "course_title": course.title,
            "tenant_id": session.tenant_id,
            "status": "queued",
            "total": len(items),
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "current_item": "",
            "progress_msg_id": progress_msg_id,
        }
        self.db.create_job(job)
        self.db.create_job_items(job_id, [self._item_row(it) for it in items])
        self.queue.push(job_id)
        log.info("job created %s user=%s course=%s items=%d",
                 job_id, tg_id, course.title, len(items))
        return self.get_job(job_id, tg_id)  # type: ignore[return-value]

    @staticmethod
    def _item_row(it: ContentItem) -> dict:
        return {
            "content_id": it.content_id,
            "title": it.title,
            "type": it.type,
            "chapter": it.chapter,
            "reference": it.reference,
        }

    # ------------------------------------------------------------ reads

    def get_job(self, job_id: str, tg_id: int) -> dict:
        job = self.db.get_job(job_id, tg_id)
        if not job:
            raise AppError("not_found", "Job not found.")
        return job

    def get_job_items(self, job_id: str, tg_id: int) -> list[dict]:
        self.get_job(job_id, tg_id)  # ownership check
        return self.db.get_job_items(job_id)

    def get_item(self, job_id: str, tg_id: int, item_id: int) -> dict:
        self.get_job(job_id, tg_id)  # ownership check
        item = self.db.get_item(item_id, job_id)
        if not item:
            raise AppError("not_found", "Item not found.")
        return item

    def history(self, tg_id: int) -> list[dict]:
        return self.db.list_jobs(tg_id, limit=50)

    # ------------------------------------------------------------ actions

    def cancel(self, job_id: str, tg_id: int) -> dict:
        job = self.get_job(job_id, tg_id)
        if job["status"] not in ACTIVE_STATUSES:
            raise AppError("invalid_input", "Job is not active.")
        self.db.update_job(job_id, status="cancelled", current_item="")
        for item in self.db.get_job_items(job_id, status="queued"):
            self.db.update_item(item["item_id"], status="cancelled")
        log.info("job cancelled %s user=%s", job_id, tg_id)
        return self.get_job(job_id, tg_id)

    def retry_item(self, job_id: str, tg_id: int, item_id: int) -> dict:
        item = self.get_item(job_id, tg_id, item_id)
        if item["status"] not in ("failed", "skipped", "cancelled"):
            raise AppError("invalid_input", "Item is not in a retryable state.")
        self.db.reset_item(item_id)
        job = self.get_job(job_id, tg_id)
        if job["status"] not in ACTIVE_STATUSES:
            self.db.update_job(job_id, status="queued")
            self.queue.push(job_id)
        return self.get_job(job_id, tg_id)

    def skip_item(self, job_id: str, tg_id: int, item_id: int) -> dict:
        self.get_item(job_id, tg_id, item_id)
        self.db.update_item(item_id, status="skipped")
        return self.get_job(job_id, tg_id)

    # ------------------------------------------------------------ stats

    def active_count(self) -> int:
        return len(self.db.list_active_jobs())

    def global_full(self) -> bool:
        return self.active_count() >= self.cfg.max_active_jobs

    def requeue_all_active(self) -> None:
        for job in self.db.list_active_jobs():
            self.queue.push(job["job_id"])
        log.info("requeued %d active job(s)", len(self.db.list_active_jobs()))

    def progress_text(self, job: dict) -> str:
        """PRD section 16 progress message template."""
        total = job["total"] or 0
        done = job["completed"] + job["failed"] + job["cancelled"]
        remaining = max(0, total - done)
        status_icon = {
            "queued": "⏳", "processing": "⚙️", "completed": "✅",
            "failed": "❌", "cancelled": "🚫",
        }.get(job["status"], "⚙️")
        lines = [
            f"{status_icon} <b>JOB {job['job_id']}</b>",
            f"Course: {job['course_title']}",
            "━━━━━━━━━━━━━━━━",
            f"Completed: {job['completed']}/{total}",
            f"Failed: {job['failed']}",
            f"Remaining: {remaining}",
        ]
        if job.get("current_item"):
            lines.append(f"\nCurrent:\n{job['current_item']}")
        if job["status"] == "processing":
            lines.append("\nStatus: ⬆️ Processing...")
        elif job["status"] == "queued":
            lines.append("\nStatus: ⏳ Queued...")
        return "\n".join(lines)
