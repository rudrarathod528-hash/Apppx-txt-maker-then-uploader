"""
Minimal SQLite database — PRD section 21.

NOTE: users table me PASSWORD KA COLUMN NAHI HAI (by design).
Sirf encrypted session reference store hota hai.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from utils.helpers import now_ts
from utils.logger import get_logger

log = get_logger("db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_user_id   TEXT PRIMARY KEY,
    platform_user_id   TEXT,
    tenant_id          TEXT,
    tenant_name        TEXT,
    username           TEXT,
    encrypted_session  TEXT,
    token_expiry       INTEGER,
    created_at         INTEGER,
    updated_at         INTEGER
);

CREATE TABLE IF NOT EXISTS courses (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_user_id  TEXT,
    course_id         TEXT,
    tenant_id         TEXT,
    title             TEXT,
    meta              TEXT,
    updated_at        INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id            TEXT PRIMARY KEY,
    telegram_user_id  TEXT,
    course_id         TEXT,
    course_title      TEXT,
    tenant_id         TEXT,
    status            TEXT,
    total             INTEGER DEFAULT 0,
    completed         INTEGER DEFAULT 0,
    failed            INTEGER DEFAULT 0,
    cancelled         INTEGER DEFAULT 0,
    current_item      TEXT,
    progress_msg_id   INTEGER,
    created_at        INTEGER,
    updated_at        INTEGER
);

CREATE TABLE IF NOT EXISTS job_items (
    item_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT,
    content_id    TEXT,
    title         TEXT,
    type          TEXT,
    chapter       TEXT,
    reference     TEXT,
    status        TEXT,
    retry_count   INTEGER DEFAULT 0,
    error_code    TEXT,
    error_message TEXT,
    created_at    INTEGER,
    updated_at    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_jobs_user ON jobs(telegram_user_id);
CREATE INDEX IF NOT EXISTS idx_items_job ON job_items(job_id);
CREATE INDEX IF NOT EXISTS idx_courses_user ON courses(telegram_user_id, course_id);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        log.info("database ready: %s", path)

    # ------------------------------------------------------------- users

    def upsert_user(
        self,
        tg_id: int,
        platform_user_id: str,
        tenant_id: str,
        tenant_name: str,
        username: str,
        encrypted_session: str,
        token_expiry: int,
    ) -> None:
        ts = now_ts()
        self.conn.execute(
            """INSERT INTO users (telegram_user_id, platform_user_id, tenant_id,
                                  tenant_name, username, encrypted_session,
                                  token_expiry, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)
               ON CONFLICT(telegram_user_id) DO UPDATE SET
                 platform_user_id=excluded.platform_user_id,
                 tenant_id=excluded.tenant_id,
                 tenant_name=excluded.tenant_name,
                 username=excluded.username,
                 encrypted_session=excluded.encrypted_session,
                 token_expiry=excluded.token_expiry,
                 updated_at=excluded.updated_at""",
            (
                str(tg_id), platform_user_id, tenant_id, tenant_name, username,
                encrypted_session, token_expiry, ts, ts,
            ),
        )
        self.conn.commit()

    def get_user(self, tg_id: int) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM users WHERE telegram_user_id=?", (str(tg_id),)
        ).fetchone()
        return dict(row) if row else None

    def clear_session(self, tg_id: int) -> None:
        self.conn.execute(
            "UPDATE users SET encrypted_session=NULL, token_expiry=NULL, updated_at=? "
            "WHERE telegram_user_id=?",
            (now_ts(), str(tg_id)),
        )
        self.conn.commit()

    def remember_tenant(self, tg_id: int, tenant_id: str, tenant_name: str) -> None:
        ts = now_ts()
        self.conn.execute(
            """INSERT INTO users (telegram_user_id, tenant_id, tenant_name, created_at, updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(telegram_user_id) DO UPDATE SET
                 tenant_id=excluded.tenant_id, tenant_name=excluded.tenant_name,
                 updated_at=excluded.updated_at""",
            (str(tg_id), tenant_id, tenant_name, ts, ts),
        )
        self.conn.commit()

    # ------------------------------------------------------------- courses

    def save_courses(self, tg_id: int, tenant_id: str, courses: list[dict]) -> None:
        ts = now_ts()
        for c in courses:
            self.conn.execute(
                """INSERT INTO courses (telegram_user_id, course_id, tenant_id, title, meta, updated_at)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                     meta=excluded.meta, updated_at=excluded.updated_at""",
                (
                    str(tg_id), str(c.get("course_id", "")), tenant_id,
                    c.get("title", ""), str(c.get("meta", {})), ts,
                ),
            )
        self.conn.commit()

    def list_courses(self, tg_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM courses WHERE telegram_user_id=? ORDER BY title", (str(tg_id),)
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- jobs

    def create_job(self, job: dict) -> None:
        self.conn.execute(
            """INSERT INTO jobs (job_id, telegram_user_id, course_id, course_title,
                                 tenant_id, status, total, completed, failed, cancelled,
                                 current_item, progress_msg_id, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job["job_id"], str(job["telegram_user_id"]), job.get("course_id", ""),
                job.get("course_title", ""), job.get("tenant_id", ""),
                job.get("status", "queued"), job.get("total", 0),
                job.get("completed", 0), job.get("failed", 0), job.get("cancelled", 0),
                job.get("current_item", ""), job.get("progress_msg_id"),
                now_ts(), now_ts(),
            ),
        )
        self.conn.commit()

    def get_job(self, job_id: str, tg_id: int | None = None) -> dict | None:
        if tg_id is not None:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE job_id=? AND telegram_user_id=?",
                (job_id, str(tg_id)),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_job(self, job_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = now_ts()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE jobs SET {cols} WHERE job_id=?", (*fields.values(), job_id)
        )
        self.conn.commit()

    def list_jobs(self, tg_id: int, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE telegram_user_id=? ORDER BY created_at DESC LIMIT ?",
            (str(tg_id), limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_active_jobs(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE status IN ('queued','processing')"
        ).fetchall()
        return [dict(r) for r in rows]

    def requeue_interrupted(self) -> int:
        """Restart ke baad processing items/jobs wapas queue me."""
        n = self.conn.execute(
            "UPDATE job_items SET status='queued' WHERE status='processing'"
        ).rowcount
        self.conn.execute(
            "UPDATE jobs SET status='queued' WHERE status='processing'"
        )
        self.conn.commit()
        return n

    def prune_jobs(self, retention_days: int) -> int:
        cutoff = now_ts() - retention_days * 86400
        rows = self.conn.execute(
            "SELECT job_id FROM jobs WHERE created_at < ? AND status IN "
            "('completed','failed','cancelled')",
            (cutoff,),
        ).fetchall()
        ids = [r["job_id"] for r in rows]
        for jid in ids:
            self.conn.execute("DELETE FROM job_items WHERE job_id=?", (jid,))
            self.conn.execute("DELETE FROM jobs WHERE job_id=?", (jid,))
        self.conn.commit()
        return len(ids)

    # ------------------------------------------------------------- job items

    def create_job_items(self, job_id: str, items: list[dict]) -> None:
        ts = now_ts()
        self.conn.executemany(
            """INSERT INTO job_items (job_id, content_id, title, type, chapter,
                                      reference, status, retry_count, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                (
                    job_id, str(it.get("content_id", "")), it.get("title", ""),
                    it.get("type", "other"), it.get("chapter", ""),
                    it.get("reference", ""), "queued", 0, ts, ts,
                )
                for it in items
            ],
        )
        self.conn.commit()

    def get_job_items(self, job_id: str, status: str | None = None) -> list[dict]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM job_items WHERE job_id=? AND status=? ORDER BY item_id",
                (job_id, status),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM job_items WHERE job_id=? ORDER BY item_id", (job_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_item(self, item_id: int, job_id: str | None = None) -> dict | None:
        if job_id:
            row = self.conn.execute(
                "SELECT * FROM job_items WHERE item_id=? AND job_id=?",
                (item_id, job_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT * FROM job_items WHERE item_id=?", (item_id,)
            ).fetchone()
        return dict(row) if row else None

    def update_item(self, item_id: int, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = now_ts()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute(
            f"UPDATE job_items SET {cols} WHERE item_id=?", (*fields.values(), item_id)
        )
        self.conn.commit()

    def reset_item(self, item_id: int) -> None:
        self.update_item(item_id, status="queued", error_code=None, error_message=None)

    # ------------------------------------------------------------- stats

    def stats(self) -> dict:
        return {
            "users": self.conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"],
            "active_sessions": self.conn.execute(
                "SELECT COUNT(*) c FROM users WHERE encrypted_session IS NOT NULL "
                "AND token_expiry > ?", (now_ts(),)
            ).fetchone()["c"],
            "active_jobs": self.conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE status IN ('queued','processing')"
            ).fetchone()["c"],
            "failed_jobs": self.conn.execute(
                "SELECT COUNT(*) c FROM jobs WHERE status='failed'"
            ).fetchone()["c"],
            "total_jobs": self.conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"],
            "failed_items": self.conn.execute(
                "SELECT COUNT(*) c FROM job_items WHERE status='failed'"
            ).fetchone()["c"],
        }

    def close(self) -> None:
        self.conn.close()
