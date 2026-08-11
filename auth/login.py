"""
Login flow logic — PRD sections 1-2.

Credentials: sirf authentication ke liye; password turant discard.
Password kabhi log/store nahi hota.
"""
from __future__ import annotations

from dataclasses import dataclass

from config import Config
from platforms.client import PlatformClient
from platforms.models import SessionData, Tenant
from platforms.registry import TenantRegistry
from utils.logger import get_logger
from utils.security import AppError

log = get_logger("login")


@dataclass
class LoginResult:
    ok: bool
    session: SessionData | None = None
    error: AppError | None = None


class LoginService:
    def __init__(self, cfg: Config, registry: TenantRegistry, client: PlatformClient):
        self.cfg = cfg
        self.registry = registry
        self.client = client

    async def attempt(self, tenant: Tenant, username: str, password: str) -> LoginResult:
        """Live platform se authenticate; password keval yahan use hota hai."""
        try:
            session = await self.client.login(tenant, username, password)
        except AppError as e:
            log.info("login failed tenant=%s user=%s code=%s", tenant.name, username, e.code)
            return LoginResult(ok=False, error=e)
        except Exception as e:  # unexpected — sanitize
            log.error("login unexpected err=%s", e.__class__.__name__)
            return LoginResult(ok=False, error=AppError("unknown", "Login failed. Please try again."))
        finally:
            password = ""  # memory se turant discard
        log.info("login ok tenant=%s user=%s", tenant.name, username)
        return LoginResult(ok=True, session=session)

    def find_tenant(self, name_or_url: str) -> Tenant | None:
        """Institute name ya API URL se tenant find karta hai."""
        q = name_or_url.strip()
        if not q:
            return None
        if q.startswith("http://") or q.startswith("https://"):
            found = self.registry.find_by_api(q)
            if found:
                return found
            # custom tenant (manual URL)
            host = q.split("//")[1].split("/")[0]
            return Tenant(name=host, api_base=q.rstrip("/"))
        found = self.registry.search(q, limit=1)
        return found[0] if found else None
