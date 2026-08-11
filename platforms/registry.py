"""
Tenant registry — appxapis.json (2422+ ClassX/AppX white-label institutes).

Institute name se API base URL find karta hai (fuzzy match).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from platforms.models import Tenant
from utils.logger import get_logger

log = get_logger("registry")


def _normalize(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


class TenantRegistry:
    def __init__(self, path: str):
        self.tenants: list[Tenant] = []
        self._by_name: dict[str, Tenant] = {}
        self._by_host: dict[str, Tenant] = {}
        self._load(path)

    def _load(self, path: str) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        seen: set[str] = set()
        for entry in data:
            name = str(entry.get("name", "")).strip()
            api = str(entry.get("api", "")).strip().rstrip("/")
            if not name or not api or api in seen:
                continue
            seen.add(api)
            tenant = Tenant(name=name, api_base=api)
            self.tenants.append(tenant)
            self._by_name[_normalize(name)] = tenant
            try:
                host = api.split("//")[1].split("/")[0]
                self._by_host.setdefault(host, tenant)
            except IndexError:
                pass
        log.info("registry loaded: %d tenants", len(self.tenants))

    def count(self) -> int:
        return len(self.tenants)

    def add(self, tenant: Tenant) -> None:
        """Extra tenant register karta hai (e.g. mock demo institute)."""
        key = _normalize(tenant.name)
        if key not in self._by_name:
            self.tenants.insert(0, tenant)
            self._by_name[key] = tenant

    def search(self, query: str, limit: int = 10) -> list[Tenant]:
        q = _normalize(query)
        if not q:
            return []
        exact = self._by_name.get(q)
        result: list[Tenant] = []
        if exact:
            result.append(exact)
        # startswith
        for t in self.tenants:
            if t.name.lower().startswith(query.lower()) and (exact is None or t.name != exact.name):
                result.append(t)
            if len(result) >= limit:
                return result[:limit]
        # substring
        for t in self.tenants:
            if q in _normalize(t.name) and (exact is None or t is not exact) and t not in result:
                result.append(t)
            if len(result) >= limit:
                break
        return result[:limit]

    def find_by_host(self, host: str) -> Tenant | None:
        return self._by_host.get(host.lower())

    def find_by_api(self, api_base: str) -> Tenant | None:
        api_base = api_base.rstrip("/")
        try:
            host = api_base.split("//")[1].split("/")[0]
        except IndexError:
            return None
        return self.find_by_host(host) or (
            self._by_name.get(_normalize(api_base.rsplit("/", 1)[-1]))
        )
