"""
Automatic cleanup worker — PRD section 20.

Har scheduled interval par:
- TTL (FILE_TTL_HOURS) se purani temp files delete
- Completed/cancelled jobs ki files cleanup log me update
- Purane job rows DB se prune (JOBS_RETENTION_DAYS)
"""
from __future__ import annotations

import asyncio
import shutil
import time
from datetime import datetime
from pathlib import Path

from config import Config
from storage.database import Database
from utils.logger import get_logger

log = get_logger("cleanup")


class CleanupWorker:
    def __init__(self, cfg: Config, db: Database):
        self.cfg = cfg
        self.db = db
        self.log_path = Path(cfg.database_path).parent / "cleanup.log"
        self._task: asyncio.Task | None = None
        self._stopping = False

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="appx-cleanup")

    async def stop(self) -> None:
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        interval = max(5, self.cfg.cleanup_interval_min * 60)
        while not self._stopping:
            try:
                await asyncio.sleep(interval)
                self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error("cleanup error err=%s", e.__class__.__name__)

    def run_once(self) -> dict:
        ttl_sec = self.cfg.file_ttl_hours * 3600
        now = time.time()
        deleted_files = 0
        freed_bytes = 0

        for root in (Path(self.cfg.export_dir), Path(self.cfg.job_dir)):
            if not root.exists():
                continue
            for item in root.rglob("*"):
                try:
                    if item.is_file() and now - item.stat().st_mtime > ttl_sec:
                        freed_bytes += item.stat().st_size
                        item.unlink()
                        deleted_files += 1
                    elif item.is_dir() and now - item.stat().st_mtime > ttl_sec:
                        shutil.rmtree(item, ignore_errors=True)
                        deleted_files += 1
                except OSError:
                    continue

        pruned_jobs = self.db.prune_jobs(self.cfg.jobs_retention_days)

        if deleted_files or pruned_jobs:
            entry = (
                f"{datetime.now().isoformat()} | deleted={deleted_files} "
                f"freed={freed_bytes} bytes | pruned_jobs={pruned_jobs}\n"
            )
            try:
                with self.log_path.open("a", encoding="utf-8") as fh:
                    fh.write(entry)
            except OSError:
                pass
            log.info("cleanup done deleted=%d pruned_jobs=%d", deleted_files, pruned_jobs)
        return {"deleted_files": deleted_files, "freed_bytes": freed_bytes, "pruned_jobs": pruned_jobs}
