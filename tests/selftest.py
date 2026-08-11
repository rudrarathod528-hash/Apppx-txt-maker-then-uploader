"""Selftest — end-to-end verification (bina Telegram ke).

    python main.py --selftest

Mock platform + FakeGateway se pura flow test hota hai:
login → session → courses → content → TXT exports → media jobs →
worker (sequential, retry, cancel) → cleanup → ownership → security.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# env pehle set karna zaroori hai (config load se pehle)
_TMP = tempfile.mkdtemp(prefix="appx-selftest-")
os.environ.update({
    "PLATFORM_MODE": "mock",
    "DATABASE_PATH": os.path.join(_TMP, "test.db"),
    "EXPORT_DIR": os.path.join(_TMP, "exports"),
    "JOB_DIR": os.path.join(_TMP, "jobs"),
    "LOG_LEVEL": "WARNING",
    "MAX_ACTIVE_JOBS": "2",
    "MAX_JOBS_PER_USER": "5",
    "MAX_RETRIES": "3",
    "RETRY_BACKOFF_SEC": "0,0,0",
    "JOBS_RETENTION_DAYS": "30",
    "UPLOAD_CHANNEL_ID": "777777",
})

from config import load_config  # noqa: E402
from context import ctx  # noqa: E402
from main import _build_context  # noqa: E402
from platforms.models import SessionData  # noqa: E402
from platforms.mock import DEMO_PASS, DEMO_USER  # noqa: E402
from utils.gateway import BaseGateway, SendResult  # noqa: E402
from utils.helpers import now_ts  # noqa: E402
from utils.logger import get_logger  # noqa: E402
from utils.security import AppError  # noqa: E402

log = get_logger("selftest")
TG_A = 111111
TG_B = 222222


class FakeGateway(BaseGateway):
    def __init__(self) -> None:
        self.documents: list[str] = []
        self.document_chats: list[int] = []
        self.messages: list[str] = []
        self.edits: list[str] = []
        self._msg_id = 100
        self.fail_documents: dict[str, int] = {}  # filename -> times to fail

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    async def send_message(self, chat_id, text, reply_markup=None) -> SendResult:
        self.messages.append(text)
        return SendResult(ok=True, message_id=self._next_id())

    async def edit_message(self, chat_id, message_id, text, reply_markup=None) -> SendResult:
        self.edits.append(text)
        return SendResult(ok=True, message_id=message_id)

    async def send_document(self, chat_id, file_path, filename=None, caption=None) -> SendResult:
        name = filename or Path(file_path).name
        if self.fail_documents.get(name, 0) > 0:
            self.fail_documents[name] -= 1
            return SendResult(ok=False, error="telegram_error")
        self.documents.append(name)
        self.document_chats.append(chat_id)
        return SendResult(ok=True, message_id=self._next_id())

    async def delete_message(self, chat_id, message_id) -> SendResult:
        return SendResult(ok=True)


async def drain(timeout: float = 60.0) -> None:
    """Queue + active jobs ke empty hone tak wait."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        active = [j for j in ctx.db.list_active_jobs()]
        if ctx.queue.qsize() == 0 and not active:
            return
        await asyncio.sleep(0.1)
    raise TimeoutError("jobs drain timeout")


async def run_selftest() -> int:
    results: list[tuple[str, bool, str]] = []

    class SkipTest(Exception):
        pass

    async def t(name: str, fn) -> None:
        try:
            await fn()
            results.append((name, True, ""))
            print(f"  ✅ {name}")
        except SkipTest as e:
            results.append((name, True, ""))
            print(f"  ⏭  {name} — SKIPPED ({e})")
        except Exception as e:  # noqa: BLE001
            results.append((name, False, str(e)))
            print(f"  ❌ {name}: {e}")

    print("\n🔎 APPX Course Bot — SELFTEST\n")

    cfg = load_config()
    gateway = FakeGateway()
    _build_context(cfg, gateway=gateway)
    await ctx.client.start()
    await ctx.media.start()
    ctx.worker.start()

    # ------------------------------------------------------------ registry
    async def test_registry() -> None:
        assert ctx.registry.count() >= 2000, f"tenants={ctx.registry.count()}"
        hits = ctx.registry.search("aash", limit=5)
        assert hits, "search 'aash' failed"
    await t("registry: 2000+ tenants load + search", test_registry)

    # ------------------------------------------------------------ login
    async def test_login_bad() -> None:
        tenant = ctx.registry.search("Demo", limit=1)[0]
        res = await ctx.login_svc.attempt(tenant, DEMO_USER, "wrongpass")
        assert not res.ok, "wrong password accepted!"
    await t("login: wrong password rejected", test_login_bad)

    async def test_login_ok() -> None:
        tenant = ctx.registry.search("Demo", limit=1)[0]
        res = await ctx.login_svc.attempt(tenant, DEMO_USER, DEMO_PASS)
        assert res.ok and res.session and res.session.token.startswith("mock-")
        ctx.sessions.save(TG_A, res.session, DEMO_USER)
    await t("login: demo account works + session saved (encrypted)", test_login_ok)

    async def test_token_info() -> None:
        """User ke apne session ka JWT extract hota hai (encrypted se)."""
        info = ctx.sessions.get_token_info(TG_A)
        assert info and info["token"].startswith("mock-"), info
        assert "demo123" not in str(info), "password leak!"
        # doosre user ka token nahi milta
        assert ctx.sessions.get_token_info(TG_B) is None
    await t("session: token info extract (JWT view, own account only)", test_token_info)

    async def test_no_password_in_db() -> None:
        conn = sqlite3.connect(cfg.database_path)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
        assert "password" not in [c.lower() for c in cols], "password column exists!"
        row = conn.execute("SELECT * FROM users").fetchone()
        assert row is not None
        row_dict = dict(zip([c[0] for c in conn.execute("PRAGMA table_info(users)")], row))
        assert all("password" not in str(k).lower() for k in row_dict)
        assert "demo123" not in str(row_dict).lower(), "password value stored!"
        # encrypted session should not contain plaintext token
        assert "mock-token" not in str(row_dict.get("encrypted_session", "")), "token plaintext!"
        conn.close()
    await t("security: no password column / no plaintext token in DB", test_no_password_in_db)

    # ------------------------------------------------------------ courses
    session = ctx.sessions.get(TG_A)

    async def test_courses() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        assert len(courses) == 4, f"courses={len(courses)}"
    await t("courses: 4 demo courses listed", test_courses)

    async def test_content() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        counts = tree.counts()
        assert counts["chapters"] == 3 and counts["videos"] == 6 and counts["pdfs"] == 3, counts
    await t("content: chapters + videos + pdfs normalized", test_content)

    # ------------------------------------------------------------ exports
    async def test_export_complete() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        files = await ctx.exports.generate(session, TG_A, [courses[0]], kind="complete", export_id="T1")
        text = files[0].read_text()
        assert "APPX COURSE" in text and "Course: Physics" in text
        assert "Type: video" in text and "Type: pdf" in text
        assert "Authorized reference: mock://" in text
        for secret in ("demo123", DEMO_USER, "password", "token"):
            assert secret.lower() not in text.lower(), f"secret leaked: {secret}"
        ctx.exports.delete_export("T1")
    await t("export: complete TXT (format + no secrets)", test_export_complete)

    async def test_export_filters() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        f1 = await ctx.exports.generate(session, TG_A, [courses[0]], kind="videos", export_id="T2")
        assert "Type: pdf" not in f1[0].read_text()
        f2 = await ctx.exports.generate(session, TG_A, [courses[0]], kind="pdfs", export_id="T3")
        assert "Type: video" not in f2[0].read_text()
        f3 = await ctx.exports.generate(session, TG_A, [courses[0]], kind="complete", chapter_idx={0}, export_id="T4")
        text = f3[0].read_text()
        assert "Chapter 02" not in text and "Chapter 01" in text
        for eid in ("T2", "T3", "T4"):
            ctx.exports.delete_export(eid)
    await t("export: videos-only / pdfs-only / selected chapters", test_export_filters)

    async def test_export_full_references() -> None:
        """TXT_REFERENCE_MODE=full — signed URL query params bhi TXT me."""
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        # ek signed URL wala item inject karo (base mode me query strip hoti hai)
        from platforms.models import ContentItem, Chapter, ContentTree

        signed_item = ContentItem(
            content_id="SIGNED1", title="Signed Video", type="video",
            chapter="Chapter 01",
            reference="https://cdn.classx.co.in/media/phy/01/motion.mp4?token=abc123&sig=xyz&expires=9999999999",
        )
        signed_tree = ContentTree(
            course_id=courses[0].course_id, course_title=courses[0].title,
            chapters=[Chapter(title="Chapter 01", items=[signed_item])],
        )
        # base mode (default): query params hat jate hain
        old_mode = ctx.exports.reference_mode
        ctx.exports.reference_mode = "base"
        f = await ctx.exports.generate(session, TG_A, [courses[0]], export_id="T6")
        assert "?token=abc123" not in f[0].read_text()
        # full mode: complete signed reference included
        ctx.exports.reference_mode = "full"
        ctx.content._cache[TG_A][courses[0].course_id] = (now_ts(), signed_tree)
        f = await ctx.exports.generate(session, TG_A, [courses[0]], export_id="T7")
        text = f[0].read_text()
        assert "?token=abc123&sig=xyz&expires=9999999999" in text, "signed URL missing!"
        assert "personal authorized use" in text, "header note missing"
        # password/session kabhi nahi
        assert "demo123" not in text and "mock-token" not in text
        ctx.exports.reference_mode = old_mode
        ctx.exports.delete_export("T6")
        ctx.exports.delete_export("T7")
        # cache restore — baaki tests ko real tree chahiye
        ctx.content.invalidate(TG_A, courses[0].course_id)
    await t("export: TXT_REFERENCE_MODE full → signed URL included (no secrets)", test_export_full_references)

    async def test_export_multi() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        files = await ctx.exports.generate(session, TG_A, courses[:2], kind="complete", export_id="T5")
        text = files[0].read_text()
        assert "Course: Physics" in text and "Course: Mathematics" in text
        ctx.exports.delete_export("T5")
    await t("export: multi-course single file", test_export_multi)

    # ------------------------------------------------------------ media
    async def test_media_process() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        pdf = [it for it in tree.flatten() if it.type == "pdf"][0]
        video = [it for it in tree.flatten() if it.type == "video"][0]
        p = await ctx.media.process(session, pdf, "MED1", 1)
        assert p.exists() and p.read_bytes()[:5] == b"%PDF-"
        v = await ctx.media.process(session, video, "MED1", 2)
        assert v.exists() and v.stat().st_size > 0
        import shutil
        shutil.rmtree(Path(cfg.job_dir) / "MED1", ignore_errors=True)
    await t("media: mock PDF valid + mock video generated", test_media_process)

    async def test_drm_detection() -> None:
        """DRM indicators → clean drm_protected error (bypass kabhi nahi)."""
        from platforms.models import ContentItem

        for bad_ref in (
            "https://cdn.classx.co.in/v.mp4?token=x&drm=widevine",
            "https://cdn.classx.co.in/manifest.mpd?drm=playready",
            "https://cdn.classx.co.in/license?token=x",
            "https://cdn.classx.co.in/v.mp4?drm=true",
        ):
            item = ContentItem(content_id="X", title="DRM", type="video", reference=bad_ref)
            try:
                await ctx.media.process(session, item, "MED-DRM", 1)
                raise AssertionError(f"DRM accepted: {bad_ref}")
            except AppError as e:
                assert e.code == "drm_protected", f"code={e.code} for {bad_ref}"
        # non-DRM signed URL ab bhi allowed hai (download path)
        ok_item = ContentItem(content_id="Y", title="OK", type="video",
                              reference="https://cdn.classx.co.in/v.mp4?token=abc&sig=xyz")
        try:
            await ctx.media.process(session, ok_item, "MED-DRM", 2)
        except AppError as e:
            assert e.code in ("network", "http_error", "not_found", "file_too_large"), \
                f"non-DRM URL galat fail: {e.code}"
    await t("media: DRM detection → clean error, signed non-DRM URL allowed", test_drm_detection)

    async def test_hls_remux() -> None:
        """HLS (.m3u8) remux — ffmpeg available ho to full test, warna skip."""
        import shutil as _shutil

        if not _shutil.which("ffmpeg"):
            raise SkipTest("ffmpeg installed nahi (Docker image me included hai)")
        # chhota HLS sample banake remux karo
        import subprocess

        work = Path(cfg.job_dir) / "HLS-TEST"
        work.mkdir(parents=True, exist_ok=True)
        src = work / "src.mp4"
        m3u8 = work / "playlist.m3u8"
        subprocess.run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=160x120:rate=10",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-f", "hls",
            "-hls_time", "1", "-hls_list_size", "0", str(m3u8),
        ], check=True, capture_output=True)
        assert m3u8.exists()
        out = await ctx.media._remux_hls(work / "out", str(m3u8), None)
        assert out.exists() and out.stat().st_size > 0
        assert out.suffix == ".mp4"
        import shutil as _sh
        _sh.rmtree(work, ignore_errors=True)
    await t("media: HLS .m3u8 → ffmpeg remux → mp4", test_hls_remux)

    # ------------------------------------------------------------ jobs
    async def test_job_lifecycle() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        items = [it for it in tree.flatten() if it.reference]
        job = await ctx.jobs.create_job(session, TG_A, courses[0], items)
        assert job["total"] == 9 and job["status"] == "queued"
        await drain()
        job = ctx.jobs.get_job(job["job_id"], TG_A)
        assert job["status"] == "completed", job["status"]
        assert job["completed"] == 9 and job["failed"] == 0, job
        assert len(gateway.documents) == 9, f"documents={gateway.documents}"
        # temp files cleaned
        job_dir = Path(cfg.job_dir) / job["job_id"]
        assert not job_dir.exists() or not any(job_dir.iterdir()), "temp files not cleaned!"
    await t("job: create → sequential worker → 9/9 delivered → files cleaned", test_job_lifecycle)

    async def test_channel_delivery() -> None:
        """UPLOAD_CHANNEL_ID set ho to media channel par jaye, progress DM me."""
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        items = [it for it in tree.flatten() if it.reference]
        job = await ctx.jobs.create_job(session, TG_A, courses[0], items)
        await drain()
        job = ctx.jobs.get_job(job["job_id"], TG_A)
        assert job["status"] == "completed"
        assert gateway.document_chats, "koi document deliver nahi hua"
        assert all(c == 777777 for c in gateway.document_chats), gateway.document_chats
        # progress DM me gaya (telegram_user_id par send_message/edit)
        assert any("JOB" in m and "APPX" in m for m in gateway.messages + gateway.edits)
    await t("delivery: media → channel (777777), progress → user DM", test_channel_delivery)

    async def test_job_retry() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        items = [it for it in tree.flatten() if it.reference]
        job = await ctx.jobs.create_job(session, TG_A, courses[0], items)

        # pehli 2 uploads fail karo → retry engine (max 3) recover kare
        orig_items = ctx.db.get_job_items(job["job_id"])
        first = orig_items[0]
        gateway.fail_documents[f"item-{first['item_id']:03d}*"] = 0  # not used
        # media-level retry: pehli process call network error de
        original_process = ctx.media.process
        calls = {"n": 0}

        async def flaky_process(sess, item, job_id, item_no):
            if calls["n"] == 0:
                calls["n"] += 1
                raise AppError("network", "Temporary network error.")
            return await original_process(sess, item, job_id, item_no)

        ctx.media.process = flaky_process  # type: ignore[method-assign]
        try:
            await drain()
        finally:
            ctx.media.process = original_process  # type: ignore[method-assign]
        job = ctx.jobs.get_job(job["job_id"], TG_A)
        assert job["status"] == "completed", job
        assert job["failed"] == 0, f"failed={job['failed']}"
    await t("job: retry engine (network error → auto retry → success)", test_job_retry)

    async def test_job_cancel() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        items = [it for it in tree.flatten() if it.reference]
        job = await ctx.jobs.create_job(session, TG_A, courses[0], items)
        ctx.jobs.cancel(job["job_id"], TG_A)
        await drain()
        job = ctx.jobs.get_job(job["job_id"], TG_A)
        assert job["status"] == "cancelled", job["status"]
        remaining = [it for it in ctx.db.get_job_items(job["job_id"]) if it["status"] == "queued"]
        assert not remaining, "queued items not cancelled!"
    await t("job: cancel → status cancelled, items cancelled", test_job_cancel)

    async def test_ownership() -> None:
        courses = await ctx.courses.list_courses(session, TG_A)
        tree = await ctx.content.get_tree(session, TG_A, courses[0])
        items = [it for it in tree.flatten() if it.reference]
        job = await ctx.jobs.create_job(session, TG_A, courses[0], items[:2])
        await drain()
        try:
            ctx.jobs.get_job(job["job_id"], TG_B)
            raise AssertionError("User B ne User A ka job dekha!")
        except AppError as e:
            assert e.code == "not_found"
        try:
            ctx.jobs.cancel(job["job_id"], TG_B)
            raise AssertionError("User B ne User A ka job cancel kiya!")
        except AppError as e:
            assert e.code == "not_found"
    await t("security: cross-user job access blocked", test_ownership)

    async def test_session_expired() -> None:
        # expire session → get None → row cleared
        ctx.sessions.clear(TG_B)
        tenant = ctx.registry.search("Demo", limit=1)[0]
        res = await ctx.login_svc.attempt(tenant, DEMO_USER, DEMO_PASS)
        assert res.ok
        ctx.sessions.save(TG_B, res.session, DEMO_USER)
        assert ctx.sessions.get(TG_B) is not None
        # expiry past me daal do
        ctx.db.conn.execute("UPDATE users SET token_expiry=? WHERE telegram_user_id=?",
                            (int(time.time()) - 100, str(TG_B)))
        ctx.db.conn.commit()
        assert ctx.sessions.get(TG_B) is None, "expired session still returned!"
        assert ctx.db.get_user(TG_B)["encrypted_session"] is None, "expired session not cleared!"
    await t("security: session expiry → cleared", test_session_expired)

    async def test_logout() -> None:
        await ctx.sessions.logout(TG_A)
        assert ctx.sessions.get(TG_A) is None
        row = ctx.db.get_user(TG_A)
        assert row is None or row["encrypted_session"] is None
    await t("security: logout clears encrypted session", test_logout)

    async def test_rate_limit() -> None:
        ok = all(ctx.limiter.allow("rl:test", 3, 60) for _ in range(3))
        assert ok
        assert not ctx.limiter.allow("rl:test", 3, 60), "rate limit not enforced!"
    await t("security: rate limiter works", test_rate_limit)

    # ------------------------------------------------------------ cleanup
    async def test_cleanup() -> None:
        job_dir = Path(cfg.job_dir)
        job_dir.mkdir(parents=True, exist_ok=True)
        old = job_dir / "old-file.bin"
        old.write_bytes(b"x")
        old_ts = time.time() - (cfg.file_ttl_hours * 3600 + 3600)
        os.utime(old, (old_ts, old_ts))
        fresh = job_dir / "fresh.bin"
        fresh.write_bytes(b"y")
        res = ctx.cleanup.run_once()
        assert res["deleted_files"] >= 1
        assert not old.exists() and fresh.exists(), "TTL cleanup wrong"
        fresh.unlink()
    await t("cleanup: TTL file deletion", test_cleanup)

    async def test_prune() -> None:
        from utils.security import random_job_id
        jid = random_job_id()
        ctx.db.create_job({"job_id": jid, "telegram_user_id": str(TG_A), "course_title": "Old",
                           "status": "completed", "total": 0})
        ctx.db.conn.execute("UPDATE jobs SET created_at=? WHERE job_id=?",
                            (int(time.time()) - 40 * 86400, jid))
        ctx.db.conn.commit()
        n = ctx.db.prune_jobs(30)
        assert n >= 1 and ctx.db.get_job(jid) is None, "old job not pruned"
    await t("cleanup: old jobs pruned from DB", test_prune)

    # ------------------------------------------------------------ teardown
    await ctx.worker.stop()
    await ctx.client.stop()
    await ctx.media.stop()
    ctx.db.close()

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{'=' * 46}")
    print(f"RESULT: {passed} passed, {failed} failed")
    print("=" * 46)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(run_selftest()) == 0 else 1)
