"""
Content service — PRD section 8.
Course ka content tree fetch + normalize + cache (per user per course).
"""
from __future__ import annotations

from platforms.client import PlatformClient
from platforms.models import ContentTree, Course, SessionData
from utils.helpers import now_ts
from utils.logger import get_logger
from utils.security import AppError

log = get_logger("content")


class ContentService:
    def __init__(self, client: PlatformClient, cache_ttl: int = 600):
        self.client = client
        self.cache_ttl = cache_ttl
        # tg_id -> {course_id: (timestamp, ContentTree)}
        self._cache: dict[int, dict[str, tuple[int, ContentTree]]] = {}

    async def get_tree(self, session: SessionData, tg_id: int, course: Course) -> ContentTree:
        per_user = self._cache.setdefault(tg_id, {})
        cached = per_user.get(course.course_id)
        if cached and now_ts() - cached[0] < self.cache_ttl:
            return cached[1]
        try:
            tree = await self.client.content(session, course.course_id)
        except AppError:
            raise
        if not tree.chapters:
            raise AppError("not_found", "No content available for this course.")
        per_user[course.course_id] = (now_ts(), tree)
        return tree

    def invalidate(self, tg_id: int, course_id: str | None = None) -> None:
        if course_id:
            self._cache.get(tg_id, {}).pop(course_id, None)
        else:
            self._cache.pop(tg_id, None)
