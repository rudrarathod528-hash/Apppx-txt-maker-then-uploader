"""
Platform API client — ClassX/AppX tenant APIs se baat karta hai.

Live mode: HTTP calls (aiohttp) with configurable endpoint paths.
Mock mode: MockPlatform (testing/demo).

Koi bhi credentials log nahi hote; errors sanitized hote hain.
"""
from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from config import Config
from platforms.models import Chapter, ContentItem, ContentTree, Course, SessionData, Tenant
from platforms.mock import MockPlatform
from platforms.normalizer import as_dict, deep_find, find_list, first_non_empty, get_path
from platforms.registry import TenantRegistry
from utils.logger import get_logger, safe_url
from utils.security import AppError, classify_http_error

log = get_logger("platform")

_TITLE_KEYS = ["title", "name", "course_name", "subject", "topic", "label"]
_ID_KEYS = ["id", "course_id", "_id", "content_id", "uuid", "slug", "item_id", "video_id"]
_REF_KEYS = [
    "secure_url", "video_url", "url", "m3u8", "hls_url", "stream_url",
    "pdf_url", "file_url", "download_url", "source_url", "content_url", "link",
]
_TYPE_KEYS = ["type", "content_type", "file_type", "kind", "media_type", "is_video", "is_pdf"]
_CHAPTER_KEYS = ["chapter", "chapter_title", "section", "module", "unit", "folder"]

_LOGIN_FALLBACK_PATHS = [
    "/api/v1/login", "/api/v1/user/login", "/api/login", "/api/auth/login",
    "/user/login", "/login",
]


def _detect_type(raw: Any) -> str:
    """Item type detect karta hai: video | pdf | other."""
    if isinstance(raw, dict):
        for k in _TYPE_KEYS:
            v = raw.get(k)
            if isinstance(v, str):
                vl = v.lower()
                if "video" in vl or "mp4" in vl or "m3u8" in vl or "hls" in vl:
                    return "video"
                if "pdf" in vl:
                    return "pdf"
            if isinstance(v, bool) and v and k.lower() in ("is_video",):
                return "video"
            if isinstance(v, bool) and v and k.lower() in ("is_pdf",):
                return "pdf"
    ref = first_non_empty(raw, _REF_KEYS).lower()
    if ref.endswith(".pdf") or "/pdf" in ref:
        return "pdf"
    if ref.endswith((".mp4", ".m3u8", ".mkv", ".webm", ".ts", ".mov")):
        return "video"
    return "other"


class PlatformClient:
    def __init__(self, cfg: Config, registry: TenantRegistry):
        self.cfg = cfg
        self.registry = registry
        self._mock: MockPlatform | None = None
        if cfg.platform_mode == "mock":
            self._mock = MockPlatform()
            from platforms.mock import DEMO_TENANT_NAME
            from platforms.models import Tenant as _Tenant

            registry.add(_Tenant(name=DEMO_TENANT_NAME, api_base="mock://demo"))
        self._http: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if not self._mock:
            self._http = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60),
                headers={"User-Agent": "APPX-Course-Bot/2.1"},
            )

    async def stop(self) -> None:
        if self._http:
            await self._http.close()

    # ------------------------------------------------------------ auth

    async def login(self, tenant: Tenant, username: str, password: str) -> SessionData:
        if self._mock:
            session = await self._mock.login(
                tenant.api_base, tenant.name, username, password
            )
            return session

        base = self.cfg.platform_base_url or tenant.api_base
        body = {
            self.cfg.login_username_key: username,
            self.cfg.login_password_key: password,
        }
        last_error: AppError | None = None
        for path in [self.cfg.login_path, *_LOGIN_FALLBACK_PATHS]:
            url = f"{base}{path}"
            try:
                async with self._http.post(
                    url, json=body, allow_redirects=True
                ) as resp:
                    if resp.status == 404:
                        continue  # path nahi mila — next fallback
                    try:
                        payload = await resp.json(content_type=None)
                    except Exception:
                        payload = {}
                    if resp.status >= 400:
                        last_error = classify_http_error(resp.status)
                        if resp.status in (401, 403):
                            break
                        continue
                    cookies = {k: v.value for k, v in resp.cookies.items()}
                    token = self._extract_token(payload, resp.headers)
                    if not token:
                        token = self._extract_token_from_cookies(cookies)
                    if not token:
                        last_error = AppError(
                            "invalid_login", "Login response me token nahi mila."
                        )
                        continue
                    return self._build_session(payload, token, tenant, cookies=cookies)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                log.warning("login network error host=%s err=%s", tenant.host, e.__class__.__name__)
                last_error = AppError("network", "Temporary network error.")
                break
        raise last_error or AppError("invalid_login", "Login failed. Please check your ID/password.")

    def _extract_token(self, payload: Any, headers: Any) -> str:
        for dotted in self.cfg.token_json_paths:
            val = get_path(as_dict(payload), dotted) if isinstance(payload, dict) else None
            if isinstance(val, str) and val.strip():
                return val.strip()
        # header fallback
        auth = headers.get("Authorization") or headers.get("authorization")
        if auth and auth.lower().startswith("bearer "):
            return auth.split(" ", 1)[1].strip()
        return ""

    @staticmethod
    def _extract_token_from_cookies(cookies: dict) -> str:
        """Cookie-auth platforms ke liye: token/jwt/access_token cookie."""
        for key in ("token", "jwt", "access_token", "auth_token", "session"):
            val = cookies.get(key)
            if val and val.strip():
                return val.strip()
        return ""

    def _build_session(self, payload: Any, token: str, tenant: Tenant,
                       cookies: dict | None = None) -> SessionData:
        name = first_non_empty(payload, ["name", "user_name", "full_name", "display_name", "username", "first_name"])
        user_id = first_non_empty(payload, ["user_id", "id", "userId", "uid", "uuid"])
        expiry_raw = deep_find(payload, ["expires_in", "expiry", "expires_at", "token_expiry"])
        expiry = 0
        try:
            if isinstance(expiry_raw, (int, float)):
                if expiry_raw > 1_000_000_000_000:
                    expiry = int(expiry_raw / 1000)
                else:
                    expiry = int(expiry_raw)
        except Exception:
            expiry = 0
        refresh = first_non_empty(payload, ["refresh_token", "refreshToken", "refresh-token"])
        return SessionData(
            token=token,
            user_id=str(user_id),
            tenant_id=tenant.api_base.split("//")[-1],
            tenant_name=tenant.name,
            name=name or user_id or "User",
            expiry=expiry,
            refresh_token=refresh,
            cookies=cookies or {},
        )

    async def revoke(self, session: SessionData) -> None:
        if self._mock:
            await self._mock.revoke(session.token)
            return
        # live mode: optional logout endpoint (agar ho to best-effort)
        base = self.cfg.platform_base_url or session.tenant_id
        try:
            async with self._http.post(
                f"{base}/api/v1/logout",
                headers={self.cfg.token_header: f"{self.cfg.token_scheme} {session.token}"},
            ):
                pass
        except Exception:
            pass

    # ------------------------------------------------------------ data

    async def _authorized_get(self, session: SessionData, url: str) -> Any:
        headers = {self.cfg.token_header: f"{self.cfg.token_scheme} {session.token}"}
        try:
            async with self._http.get(url, headers=headers) as resp:
                if resp.status >= 400:
                    raise classify_http_error(resp.status)
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("api error url=%s err=%s", safe_url(url), e.__class__.__name__)
            raise AppError("network", "Temporary network error.")

    async def courses(self, session: SessionData) -> list[Course]:
        if self._mock:
            return await self._mock.courses(session.token)

        base = self.cfg.platform_base_url or f"https://{session.tenant_id}"
        url = f"{base}{self.cfg.courses_path}"
        payload = await self._authorized_get(session, url)
        raw_list = find_list(payload)
        courses: list[Course] = []
        for raw in raw_list or []:
            if not isinstance(raw, dict):
                continue
            cid = first_non_empty(raw, _ID_KEYS)
            title = first_non_empty(raw, _TITLE_KEYS)
            if not cid or not title:
                continue
            courses.append(Course(course_id=cid, title=title, meta=self._course_meta(raw)))
        return courses

    @staticmethod
    def _course_meta(raw: dict) -> dict:
        meta = {}
        for key, out in (("videos_count", "videos"), ("video_count", "videos"),
                         ("pdf_count", "pdfs"), ("pdfs_count", "pdfs"),
                         ("chapter_count", "chapters"), ("chapters_count", "chapters")):
            v = raw.get(key)
            if isinstance(v, (int, float)):
                meta[out] = int(v)
        return meta

    async def content(self, session: SessionData, course_id: str) -> ContentTree:
        if self._mock:
            return await self._mock.content(session.token, course_id)

        base = self.cfg.platform_base_url or f"https://{session.tenant_id}"
        url = f"{base}{self.cfg.content_path.format(course_id=course_id)}"
        payload = await self._authorized_get(session, url)
        return self._parse_content(payload, course_id)

    def _parse_content(self, payload: Any, course_id: str) -> ContentTree:
        tree = ContentTree(course_id=course_id, course_title=course_id)
        raw_chapters = self._find_chapters(payload)
        if not raw_chapters:
            # flat list of items → single "Chapter 01"
            items = self._parse_items(payload)
            if items:
                tree.chapters.append(Chapter(title="Chapter 01", items=items))
            return tree

        for idx, raw_ch in enumerate(raw_chapters, start=1):
            ch_title = ""
            if isinstance(raw_ch, dict):
                ch_title = first_non_empty(raw_ch, _CHAPTER_KEYS + _TITLE_KEYS) or f"Chapter {idx:02d}"
                raw_items = self._find_items(raw_ch)
            else:
                ch_title = f"Chapter {idx:02d}"
                raw_items = self._find_items(raw_ch)
            items = self._parse_items(raw_items)
            if not items and isinstance(raw_ch, dict):
                # chapter dict me khud items ho sakte hain (nested lists)
                items = self._parse_items(raw_ch)
            if items:
                tree.chapters.append(Chapter(title=ch_title, items=items))
        return tree

    def _find_chapters(self, payload: Any) -> list:
        if isinstance(payload, dict):
            for key in ("chapters", "modules", "sections", "units", "topics", "batches", "classes"):
                v = payload.get(key)
                if isinstance(v, list) and v:
                    return v
        found = find_list(payload) or []
        # list of chapter-ish dicts (title + items) chahiye
        chapters = [x for x in found if isinstance(x, dict) and (
            any(k in x for k in ("chapters", "items", "videos", "content", "resources",
                                 "lectures", "lessons", "classes"))
        )]
        return chapters or []

    def _find_items(self, raw_ch: Any) -> list:
        if isinstance(raw_ch, dict):
            for key in ("items", "content", "videos", "pdfs", "resources",
                        "lectures", "lessons", "classes", "sessions", "data"):
                v = raw_ch.get(key)
                if isinstance(v, list) and v:
                    return v
            return []
        if isinstance(raw_ch, list):
            return raw_ch
        return []

    def _parse_items(self, raw_items: Any) -> list[ContentItem]:
        items: list[ContentItem] = []
        for raw in raw_items or []:
            if not isinstance(raw, dict):
                continue
            item_type = _detect_type(raw)
            ref = first_non_empty(raw, _REF_KEYS)
            cid = first_non_empty(raw, _ID_KEYS)
            title = first_non_empty(raw, _TITLE_KEYS)
            if not title:
                continue
            # bina reference wale items sirf listing me aate hain
            # (media jobs sirf reference wale items process karte hain)
            chapter = first_non_empty(raw, _CHAPTER_KEYS)
            items.append(
                ContentItem(
                    content_id=cid or f"{item_type}:{title}",
                    title=title,
                    type=item_type,
                    chapter=chapter,
                    reference=ref,
                    meta={"raw_keys": list(raw.keys())},
                )
            )
        return items
