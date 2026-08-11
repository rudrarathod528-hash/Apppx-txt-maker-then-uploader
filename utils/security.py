"""
Security utilities:
- Fernet encryption for stored session references
- Rate limiter (per telegram user)
- Error classification / sanitization
"""
from __future__ import annotations

import base64
import secrets
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

# ---------------------------------------------------------------- error codes

RETRYABLE_ERRORS = {"network", "timeout", "telegram_error", "http_5xx"}
NON_RETRYABLE_ERRORS = {
    "unauthorized",
    "forbidden",
    "not_found",
    "unsupported_media",
    "file_too_large",
    "drm_protected",
    "invalid_input",
    "unknown",
}


@dataclass
class AppError(Exception):
    """Application-level error with safe user-facing message."""

    code: str = "unknown"
    message: str = "Something went wrong."

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.code}] {self.message}"


def classify_http_error(status: int) -> AppError:
    if status == 401:
        return AppError("unauthorized", "Session invalid or expired.")
    if status == 403:
        return AppError("forbidden", "Content unavailable for this account.")
    if status == 404:
        return AppError("not_found", "Content not found.")
    if status >= 500:
        return AppError("http_5xx", "Temporary server error.")
    return AppError("http_error", f"Request failed (HTTP {status}).")


def safe_error_message(exc: BaseException) -> str:
    """User ko kabhi raw exception/token nahi dikhata."""
    if isinstance(exc, AppError):
        return exc.message
    return "Something went wrong. Please try again."


# ---------------------------------------------------------------- encryption

class Crypto:
    """Session references Fernet se encrypt hote hain.

    Key: url-safe base64 string (Fernet.generate_key() jaisi).
    """

    def __init__(self, key_b64: str | None = None, secret_file: str | None = None):
        self._key_b64 = self._load_or_create_key(key_b64, secret_file)

    @staticmethod
    def _load_or_create_key(key_b64: str | None, secret_file: str | None) -> str:
        if key_b64:
            key = key_b64.strip()
            Fernet(key)  # validate
            return key
        if secret_file:
            path = Path(secret_file)
            if path.exists():
                key = path.read_text().strip()
                Fernet(key)  # validate
                return key
            key = Fernet.generate_key().decode()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(key)
            try:
                path.chmod(0o600)
            except OSError:
                pass
            return key
        raise ValueError(
            "ENCRYPTION_KEY not set and no secret file available."
        )

    def encrypt(self, plaintext: str) -> str:
        f = Fernet(self._key_b64)
        return f.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        f = Fernet(self._key_b64)
        try:
            return f.decrypt(ciphertext.encode()).decode()
        except InvalidToken:
            raise AppError("unauthorized", "Session could not be decrypted. Please login again.")


# ---------------------------------------------------------------- rate limit

class RateLimiter:
    """Simple sliding-window rate limiter (per key)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_sec: int) -> bool:
        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > window_sec:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True

    def remaining(self, key: str, limit: int, window_sec: int) -> int:
        now = time.time()
        q = self._hits[key]
        while q and now - q[0] > window_sec:
            q.popleft()
        return max(0, limit - len(q))


# ---------------------------------------------------------------- misc

def random_job_id() -> str:
    """Job ID format: APPX-8F31 (PRD section 14)."""
    return "APPX-" + secrets.token_hex(2).upper()


def safe_slug(text: str, max_len: int = 60) -> str:
    """Filename-safe slug."""
    import re

    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text.lower()).strip("_")
    return slug[:max_len] or "item"


def secure_filename(name: str) -> str:
    """Downloaded file ka naam sanitize (path traversal blocked)."""
    import re

    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^a-zA-Z0-9._ -]", "_", name).strip(" .")
    return name[:180] or "file.bin"
