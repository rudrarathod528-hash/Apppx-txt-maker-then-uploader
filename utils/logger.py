"""
Sanitized logging — logs me kabhi bhi password/token/cookie nahi jata.
"""
from __future__ import annotations

import logging
import re
import sys
from urllib.parse import urlsplit, urlunsplit

# Known secret-ish values jo logs me kabhi nahi hone chahiye.
_SECRET_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*[^\s&\"']+"), r"\1=***"),
    (re.compile(r"(?i)(token|access_token|auth_token|jwt|api[_-]?key|session[_-]?id)\s*[=:]\s*[^\s&\"']+"), r"\1=***"),
    (re.compile(r"(?i)(authorization|cookie)[^,;\n]*"), r"\1: ***"),
]

LOG_REDACTED = "***"


def redact(text: str) -> str:
    """Common secrets ko log-line me redact karta hai."""
    if not text:
        return text
    out = text
    for pattern, repl in _SECRET_PATTERNS:
        out = pattern.sub(repl, out)
    return out


def safe_url(url: str) -> str:
    """URL se query params / fragment / userinfo hata deta hai —
    streaming URLs me signed tokens hote hain, unhe log nahi karte."""
    try:
        parts = urlsplit(url)
        clean = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        return clean
    except Exception:
        return redact(url)[:200]


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            record.msg = redact(str(record.msg))
            if record.args:
                record.args = tuple(redact(str(a)) if isinstance(a, str) else a for a in record.args)
        except Exception:
            pass
        return super().format(record)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        RedactingFormatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    )
    root.handlers = [handler]
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
