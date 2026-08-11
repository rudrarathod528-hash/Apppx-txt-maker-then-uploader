"""Application context — dependency wiring (main.py me set hota hai)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Context:
    cfg: Any = None
    db: Any = None
    registry: Any = None
    client: Any = None
    crypto: Any = None
    sessions: Any = None
    login_svc: Any = None
    courses: Any = None
    content: Any = None
    exports: Any = None
    media: Any = None
    queue: Any = None
    jobs: Any = None
    worker: Any = None
    cleanup: Any = None
    bot: Any = None
    gateway: Any = None
    limiter: Any = None
    # runtime state (per telegram user, ownership-keyed)
    stats: dict = field(default_factory=lambda: {"api_errors": 0, "tg_errors": 0})
    inst_search: dict = field(default_factory=dict)   # tg_id -> [Tenant]
    selections: dict = field(default_factory=dict)    # tg_id -> {key: set}
    _selections_holder: dict = field(default_factory=dict)

    def selection(self, tg_id: int, key: str) -> set[int]:
        self._selections_holder.setdefault(tg_id, {}).setdefault(key, set())
        return self._selections_holder[tg_id][key]


ctx = Context()
