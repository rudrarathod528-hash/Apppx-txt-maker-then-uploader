"""
Job queue — PRD section 14.

In-process asyncio queue; jobs table source of truth hai
(restart par requeue hota hai).
"""
from __future__ import annotations

import asyncio


class JobQueue:
    def __init__(self) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()

    def push(self, job_id: str) -> None:
        self._q.put_nowait(job_id)

    async def get(self) -> str:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()
