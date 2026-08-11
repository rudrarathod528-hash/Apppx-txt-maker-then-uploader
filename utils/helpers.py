"""Small shared helpers."""
from __future__ import annotations

import time


def now_ts() -> int:
    return int(time.time())


def human_size(num_bytes: int | float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def paginate(items: list, page: int, per_page: int = 8):
    """Returns (page_items, total_pages)."""
    total = len(items)
    pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, pages - 1))
    start = page * per_page
    return items[start : start + per_page], pages, page


def chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
