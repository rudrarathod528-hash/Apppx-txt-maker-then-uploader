"""
Response normalizer — ClassX jaise platforms ke JSON responses ke common
shapes ko handle karta hai:

    {"data": {...}} / {"result": [...]} / {"payload": {...}} / root arrays
    {"success": true, "data": {"token": "..."}}

Deep-key lookup case-insensitive hota hai, taaki response structure badalne
par bhi bot kaam karta rahe.
"""
from __future__ import annotations

from typing import Any


def _norm_key(k: str) -> str:
    return k.lower().replace("-", "").replace("_", "")


def deep_find(data: Any, keys: list[str]) -> Any:
    """Nested dict me se pehla matching key value return karta hai."""
    wanted = {_norm_key(k) for k in keys}
    if isinstance(data, dict):
        for k, v in data.items():
            if _norm_key(k) in wanted:
                return v
        for v in data.values():
            found = deep_find(v, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for v in data:
            found = deep_find(v, keys)
            if found is not None:
                return found
    return None


def get_path(data: dict, dotted_path: str) -> Any:
    """'data.token' style path se value nikalta hai (case-insensitive keys)."""
    parts = dotted_path.split(".")
    cur: Any = data
    for part in parts:
        if isinstance(cur, dict):
            cur = next((v for k, v in cur.items() if _norm_key(k) == _norm_key(part)), None)
        else:
            return None
        if cur is None:
            return None
    return cur


def find_list(data: Any) -> list | None:
    """Response me se pehli meaningful list nikalta hai."""
    if isinstance(data, list):
        return data if data else None
    if isinstance(data, dict):
        for k in ("data", "result", "results", "payload", "list", "items", "courses", "records"):
            v = data.get(k)
            if isinstance(v, list) and v:
                return v
        for v in data.values():
            found = find_list(v)
            if found:
                return found
    return None


def as_dict(data: Any) -> dict:
    if isinstance(data, dict):
        return data
    return {}


def first_non_empty(data: Any, keys: list[str]) -> str:
    val = deep_find(data, keys)
    if isinstance(val, (str, int, float)) and str(val).strip():
        return str(val).strip()
    return ""
