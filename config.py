"""
Configuration loader — sab kuch environment variables (.env) se aata hai.
Secrets kabhi hard-code nahi hote.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int_or_none(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return list(default or [])
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Config:
    # --- Telegram ---
    bot_token: str = ""
    admin_ids: list[int] = field(default_factory=list)
    # Delivery target: set karo to media/exports is channel me jayengi
    # (user DM ke bajaye). Channel me bot ko admin hona chahiye.
    upload_channel_id: int | None = None

    # --- Platform ---
    platform_mode: str = "live"  # live | mock
    platform_base_url: str | None = None
    login_path: str = "/api/v1/login"
    courses_path: str = "/api/v1/user/courses"
    content_path: str = "/api/v1/course/{course_id}/content"
    login_username_key: str = "username"
    login_password_key: str = "password"
    token_json_paths: list[str] = field(
        default_factory=lambda: [
            "data.token",
            "data.access_token",
            "data.auth_token",
            "data.jwt",
            "token",
            "access_token",
            "auth_token",
            "jwt",
        ]
    )
    token_header: str = "Authorization"
    token_scheme: str = "Bearer"

    # --- Storage ---
    database_path: str = str(BASE_DIR / "data" / "appx.db")
    export_dir: str = "/tmp/appx/exports"
    job_dir: str = "/tmp/appx/jobs"

    # --- Limits ---
    file_ttl_hours: int = 24
    max_upload_mb: int = 1950
    max_retries: int = 3
    max_active_jobs: int = 5
    max_jobs_per_user: int = 3
    export_mode: str = "single"  # single | separate
    # TXT me reference kaise likhein:
    #   base = sirf host+path (query params hatao — PRD §10 default, safe)
    #   full = platform-provided complete reference (signed URL bhi)
    #          personal authorized use; links expire ho sakti hain
    txt_reference_mode: str = "base"

    # --- Security ---
    encryption_key: str | None = None

    # --- Misc ---
    log_level: str = "INFO"
    registry_path: str = str(BASE_DIR / "appxapis.json")
    cleanup_interval_min: int = 60
    jobs_retention_days: int = 30
    content_cache_ttl_sec: int = 600
    media_timeout_sec: int = 900
    ffmpeg_timeout_sec: int = 1800

    # --- Rate limits (limit, window_seconds) ---
    login_rate: tuple[int, int] = (5, 300)
    api_rate: tuple[int, int] = (30, 60)
    export_rate: tuple[int, int] = (5, 600)

    # --- Retry backoff (seconds between attempts) ---
    retry_backoff: list[int] = field(default_factory=lambda: [5, 15, 30])

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.platform_mode == "live" and not self.bot_token:
            errors.append("BOT_TOKEN required (PLATFORM_MODE=live)")
        if self.platform_mode not in ("live", "mock"):
            errors.append("PLATFORM_MODE must be 'live' or 'mock'")
        if self.export_mode not in ("single", "separate"):
            errors.append("EXPORT_MODE must be 'single' or 'separate'")
        if self.txt_reference_mode not in ("base", "full"):
            errors.append("TXT_REFERENCE_MODE must be 'base' or 'full'")
        if not Path(self.registry_path).exists():
            errors.append(f"Registry file not found: {self.registry_path}")
        return errors


def load_config() -> Config:
    cfg = Config(
        bot_token=_env_str("BOT_TOKEN"),
        admin_ids=[int(x) for x in _env_list("ADMIN_IDS") if x.isdigit()],
        upload_channel_id=_env_int_or_none("UPLOAD_CHANNEL_ID"),
        platform_mode=_env_str("PLATFORM_MODE", "live").lower(),
        platform_base_url=_env_str("PLATFORM_BASE_URL") or None,
        login_path=_env_str("PLATFORM_LOGIN_PATH", "/api/v1/login"),
        courses_path=_env_str("PLATFORM_COURSES_PATH", "/api/v1/user/courses"),
        content_path=_env_str(
            "PLATFORM_CONTENT_PATH", "/api/v1/course/{course_id}/content"
        ),
        login_username_key=_env_str("PLATFORM_LOGIN_USERNAME_KEY", "username"),
        login_password_key=_env_str("PLATFORM_LOGIN_PASSWORD_KEY", "password"),
        token_json_paths=_env_list(
            "PLATFORM_TOKEN_JSON_PATH",
            [
                "data.token",
                "data.access_token",
                "data.auth_token",
                "data.jwt",
                "token",
                "access_token",
                "auth_token",
                "jwt",
            ],
        ),
        token_header=_env_str("PLATFORM_TOKEN_HEADER", "Authorization"),
        token_scheme=_env_str("PLATFORM_TOKEN_SCHEME", "Bearer"),
        database_path=_env_str("DATABASE_PATH", str(BASE_DIR / "data" / "appx.db")),
        export_dir=_env_str("EXPORT_DIR", "/tmp/appx/exports"),
        job_dir=_env_str("JOB_DIR", "/tmp/appx/jobs"),
        file_ttl_hours=_env_int("FILE_TTL_HOURS", 24),
        max_upload_mb=_env_int("MAX_UPLOAD_MB", 1950),
        max_retries=_env_int("MAX_RETRIES", 3),
        max_active_jobs=_env_int("MAX_ACTIVE_JOBS", 5),
        max_jobs_per_user=_env_int("MAX_JOBS_PER_USER", 3),
        export_mode=_env_str("EXPORT_MODE", "single").lower(),
        txt_reference_mode=_env_str("TXT_REFERENCE_MODE", "base").lower(),
        encryption_key=_env_str("ENCRYPTION_KEY") or None,
        log_level=_env_str("LOG_LEVEL", "INFO").upper(),
        registry_path=_env_str("REGISTRY_PATH", str(BASE_DIR / "appxapis.json")),
        cleanup_interval_min=_env_int("CLEANUP_INTERVAL_MIN", 60),
        jobs_retention_days=_env_int("JOBS_RETENTION_DAYS", 30),
        content_cache_ttl_sec=_env_int("CONTENT_CACHE_TTL_SEC", 600),
        media_timeout_sec=_env_int("MEDIA_TIMEOUT_SEC", 900),
        ffmpeg_timeout_sec=_env_int("FFMPEG_TIMEOUT_SEC", 1800),
        login_rate=(_env_int("LOGIN_RATE_LIMIT", 5), _env_int("LOGIN_RATE_WINDOW", 300)),
        api_rate=(_env_int("API_RATE_LIMIT", 30), _env_int("API_RATE_WINDOW", 60)),
        export_rate=(_env_int("EXPORT_RATE_LIMIT", 5), _env_int("EXPORT_RATE_WINDOW", 600)),
        retry_backoff=[int(x) for x in _env_list("RETRY_BACKOFF_SEC", ["5", "15", "30"]) if x.isdigit()],
    )
    return cfg
