"""
Course service — PRD section 6.
Authorized session se course list fetch + cache (per telegram user).
"""
from __future__ import annotations

import time

from auth.session import tenant_of
from platforms.client import PlatformClient
from platforms.models import Course, SessionData
from utils.helpers import now_ts
from utils.logger import get_logger
from utils.security import AppError

log = get_logger("courses")


class CourseService:
    def __init__(self, client: PlatformClient, cache_ttl: int = 600):
        self.client = client
        self.cache_ttl = cache_ttl
        # tg_id -> (timestamp, [Course])
        self._cache: dict[int, tuple[int, list[Course]]] = {}

    async def list_courses(self, session: SessionData, tg_id: int) -> list[Course]:
        cached = self._cache.get(tg_id)
        if cached and now_ts() - cached[0] < self.cache_ttl:
            return cached[1]
        try:
            courses = await self.client.courses(session)
        except AppError:
            raise
        self._cache[tg_id] = (now_ts(), courses)
        return courses

    async def get_course(self, session: SessionData, tg_id: int, course_idx: int) -> Course:
        courses = await self.list_courses(session, tg_id)
        if not (0 <= course_idx < len(courses)):
            raise AppError("not_found", "Course not found.")
        return courses[course_idx]

    def invalidate(self, tg_id: int) -> None:
        self._cache.pop(tg_id, None)
