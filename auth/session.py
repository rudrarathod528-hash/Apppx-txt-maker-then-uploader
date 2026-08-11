"""
Session manager — PRD section 3.

Stored data: encrypted_session reference (Fernet), token_expiry, ...
Raw password / raw token kabhi database me nahi.
"""
from __future__ import annotations

import json

from config import Config
from platforms.client import PlatformClient
from platforms.models import SessionData, Tenant
from storage.database import Database
from utils.helpers import now_ts
from utils.logger import get_logger
from utils.security import AppError, Crypto

log = get_logger("session")


class SessionManager:
    def __init__(self, cfg: Config, db: Database, client: PlatformClient, crypto: Crypto):
        self.cfg = cfg
        self.db = db
        self.client = client
        self.crypto = crypto

    def save(
        self,
        tg_id: int,
        session: SessionData,
        username: str,
    ) -> None:
        cipher = self.crypto.encrypt(json.dumps(session.to_dict()))
        self.db.upsert_user(
            tg_id=tg_id,
            platform_user_id=session.user_id or username,
            tenant_id=session.tenant_id,
            tenant_name=session.tenant_name,
            username=username,
            encrypted_session=cipher,
            token_expiry=session.expiry or (now_ts() + 86400),
        )
        log.info("session saved user=%s tenant=%s", tg_id, session.tenant_name)

    def get(self, tg_id: int) -> SessionData | None:
        """Valid session return karta hai; expired → None.

        Expiry ka source of truth DB ka token_expiry column hai
        (encrypted payload ke saath sync rakha jata hai)."""
        row = self.db.get_user(tg_id)
        if not row or not row.get("encrypted_session"):
            return None
        expiry = row.get("token_expiry") or 0
        if expiry and expiry < now_ts():
            log.info("session expired user=%s", tg_id)
            self.clear(tg_id)
            return None
        try:
            data = json.loads(self.crypto.decrypt(row["encrypted_session"]))
        except AppError:
            self.clear(tg_id)
            return None
        return SessionData.from_dict(data)

    async def refresh(self, tg_id: int) -> SessionData | None:
        """Expiry ke paas session ko refresh karne ki koshish (best-effort)."""
        session = self.get(tg_id)
        if not session:
            return None
        try:
            refreshed = await self.client._mock.refresh(session.token) if self.client._mock else None
            if refreshed:
                row = self.db.get_user(tg_id)
                self.save(tg_id, refreshed, (row or {}).get("username", ""))
                return refreshed
        except Exception:
            pass
        return session

    def get_token_info(self, tg_id: int) -> dict | None:
        """User ke apne session ka JWT/access token info (encrypted se decrypt).

        Sirf usi user ke liye (ownership = telegram_user_id). Token kabhi
        logs me nahi; isko user ke DM me dikhaya jata hai.
        """
        row = self.db.get_user(tg_id)
        if not row or not row.get("encrypted_session"):
            return None
        try:
            data = json.loads(self.crypto.decrypt(row["encrypted_session"]))
        except AppError:
            return None
        session = SessionData.from_dict(data)
        return {
            "token": session.token,
            "refresh_token": session.refresh_token,
            "cookies": session.cookies or {},
            "expiry": session.expiry or row.get("token_expiry") or 0,
            "tenant_name": session.tenant_name or row.get("tenant_name", ""),
            "name": session.name or "",
        }

    def clear(self, tg_id: int) -> None:
        self.db.clear_session(tg_id)
        log.info("session cleared user=%s", tg_id)

    async def logout(self, tg_id: int, revoke_platform: bool = True) -> None:
        session = self.get(tg_id)
        if session and revoke_platform:
            try:
                await self.client.revoke(session)
            except Exception as e:
                log.warning("revoke failed user=%s err=%s", tg_id, e.__class__.__name__)
        self.clear(tg_id)

    def requires(self, tg_id: int) -> SessionData:
        """Handler ke liye: session nahi hai to AppError unauthorized."""
        session = self.get(tg_id)
        if not session:
            raise AppError("unauthorized", "Please login first.")
        return session


# ------------------------------------------------------------------ helpers

def tenant_of(session: SessionData) -> Tenant:
    return Tenant(name=session.tenant_name, api_base=f"https://{session.tenant_id}")
