"""
APPX Course Bot — entry point (PRD v2.1)

    python main.py            → Telegram bot start (polling)
    python main.py --selftest → end-to-end selftest (bina Telegram ke)

Startup:
  - config load + validation
  - database, registry, platform client, services
  - job worker pool (MAX_ACTIVE_JOBS) + cleanup worker
  - interrupted jobs requeue
  - aiogram polling
"""
from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from auth.login import LoginService
from auth.session import SessionManager
from bot import handlers
from config import Config, load_config
from context import ctx
from jobs.manager import JobManager
from jobs.queue import JobQueue
from jobs.worker import Worker
from platforms.client import PlatformClient
from platforms.registry import TenantRegistry
from services.content import ContentService
from services.courses import CourseService
from services.export import ExportService
from services.media import MediaService
from storage.cleanup import CleanupWorker
from storage.database import Database
from utils.gateway import AiogramGateway
from utils.logger import get_logger, setup_logging
from utils.security import Crypto, RateLimiter

log = get_logger("main")


def _build_context(cfg: Config, bot=None, gateway=None) -> None:
    """Services ko wire karta hai (bot optional — selftest me FakeBot)."""
    from pathlib import Path

    db = Database(cfg.database_path)
    registry = TenantRegistry(cfg.registry_path)
    client = PlatformClient(cfg, registry)
    secret_file = str(Path(cfg.database_path).with_suffix(".secret"))
    crypto = Crypto(cfg.encryption_key, secret_file=secret_file if not cfg.encryption_key else None)
    limiter = RateLimiter()
    sessions = SessionManager(cfg, db, client, crypto)
    login_svc = LoginService(cfg, registry, client)
    courses = CourseService(client, cache_ttl=cfg.content_cache_ttl_sec)
    content = ContentService(client, cache_ttl=cfg.content_cache_ttl_sec)
    exports = ExportService(courses, content, cfg.export_dir, cfg.export_mode,
                            reference_mode=cfg.txt_reference_mode)
    media = MediaService(cfg, cfg.job_dir)
    queue = JobQueue()
    jobs = JobManager(cfg, db, queue, courses, content)
    gateway = gateway or (AiogramGateway(bot) if bot else None)
    worker = Worker(cfg, db, queue, jobs, media, gateway, sessions=sessions)
    cleanup = CleanupWorker(cfg, db)

    ctx.cfg = cfg
    ctx.db = db
    ctx.registry = registry
    ctx.client = client
    ctx.crypto = crypto
    ctx.limiter = limiter
    ctx.sessions = sessions
    ctx.login_svc = login_svc
    ctx.courses = courses
    ctx.content = content
    ctx.exports = exports
    ctx.media = media
    ctx.queue = queue
    ctx.jobs = jobs
    ctx.worker = worker
    ctx.cleanup = cleanup
    ctx.bot = bot
    ctx.gateway = gateway


async def _run_health_server():
    """Optional lightweight health server — Railway/Paas PORT env set ho to.

    Bot ka Telegram polling hi asli kaam hai; ye sirf hosting platforms ke
    health-check ke liye hai (deploy "healthy" dikhne ke liye)."""
    port = int(os.getenv("PORT", "0") or "0")
    if port <= 0:
        return None
    from aiohttp import web

    async def health(_request):
        return web.json_response({"ok": True, "service": "appx-course-bot"})

    app = web.Application()
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("health server started on :%d", port)
    return runner


async def _run_bot(cfg: Config) -> None:
    token = cfg.bot_token
    if not token:
        if cfg.platform_mode == "mock":
            token = "123456:DUMMY-TOKEN-FOR-MOCK-MODE"  # demo boot (polling fail hoga, app chalega)
        else:
            log.error("BOT_TOKEN required in live mode")
            return
    bot = Bot(token=token)
    _build_context(cfg, bot=bot)
    await ctx.client.start()
    await ctx.media.start()

    ctx.jobs.requeue_all_active()
    ctx.worker.start()
    ctx.cleanup.start()

    health_runner = await _run_health_server()

    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers.router)

    stop_event = asyncio.Event()

    def _sig(*_a) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _sig)
        except NotImplementedError:
            pass

    log.info("APPX Course Bot started (mode=%s, tenants=%d)",
             cfg.platform_mode, ctx.registry.count())

    polling = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    )
    try:
        await stop_event.wait()
    finally:
        log.info("shutting down...")
        polling.cancel()
        await asyncio.gather(polling, return_exceptions=True)
        await ctx.worker.stop()
        await ctx.cleanup.stop()
        await ctx.client.stop()
        await ctx.media.stop()
        if health_runner:
            await health_runner.cleanup()
        await bot.session.close()
        ctx.db.close()


async def _run_selftest() -> int:
    from tests.selftest import run_selftest

    return await run_selftest()


def main() -> None:
    parser = argparse.ArgumentParser(description="APPX Course Bot")
    parser.add_argument("--selftest", action="store_true",
                        help="End-to-end selftest (bina Telegram ke)")
    parser.add_argument("--check", action="store_true",
                        help="Config + registry check, phir exit")
    args = parser.parse_args()

    cfg = load_config()
    setup_logging(cfg.log_level)

    errors = cfg.validate()
    if errors and not args.selftest:
        for e in errors:
            log.error("CONFIG ERROR: %s", e)
        log.error("Fix .env (dekhein .env.example) — PLATFORM_MODE=mock se bina token bhi chal sakta hai")
        if not args.check:
            sys.exit(1)

    if args.check:
        registry = TenantRegistry(cfg.registry_path)
        print(f"Registry OK: {registry.count()} tenants")
        print(f"Mode: {cfg.platform_mode}")
        print(f"Config: {'OK' if not errors else 'INCOMPLETE (' + str(len(errors)) + ' issue(s), upar dekhein)'}")
        return

    if args.selftest:
        sys.exit(0 if asyncio.run(_run_selftest()) == 0 else 1)
        return

    asyncio.run(_run_bot(cfg))


if __name__ == "__main__":
    main()
