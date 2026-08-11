"""
Media service — PRD sections 13, 19, 36-37.

Sirf authorized/officially accessible media process hota hai:
- Direct download (http/https stream, size check, timeout)
- HLS/DASH (.m3u8) — ffmpeg `-c copy` remux (DRM-free streams)
- PDF / other formats (direct download)
- mock:// references → sample media (demo mode)

Download → process → return temp path. Caller upload + delete karta hai.
DRM bypass kabhi nahi. Unsupported → clean AppError.
"""
from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path

import aiohttp

from config import Config
from platforms.models import ContentItem, SessionData
from platforms.mock import make_sample_pdf, make_sample_video
from utils.helpers import human_size
from utils.security import secure_filename
from utils.logger import get_logger, safe_url
from utils.security import AppError

log = get_logger("media")

_DISPOSITION_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', re.IGNORECASE)


class MediaService:
    def __init__(self, cfg: Config, job_dir: str):
        self.cfg = cfg
        self.job_dir = Path(job_dir)
        self._http: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        self._http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.cfg.media_timeout_sec),
            headers={"User-Agent": "APPX-Course-Bot/2.1"},
        )

    async def stop(self) -> None:
        if self._http:
            await self._http.close()

    # ------------------------------------------------------------ entry

    async def process(self, session: SessionData, item: ContentItem, job_id: str, item_no: int) -> Path:
        """Item ka media download/process karke temp file return karta hai."""
        ref = (item.reference or "").strip()
        if not ref:
            raise AppError("not_found", "No authorized media reference available for this item.")

        dest_dir = self.job_dir / job_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"item-{item_no:03d}"

        # Authorization header sirf tenant ke apne host ko jata hai
        auth_header = None
        if session.token:
            from urllib.parse import urlsplit

            ref_host = urlsplit(ref).netloc.lower()
            tenant_host = f"https://{session.tenant_id}"
            try:
                tenant_host = urlsplit(tenant_host).netloc.lower()
            except Exception:
                tenant_host = ""
            if ref_host and ref_host == tenant_host:
                auth_header = {"Authorization": f"Bearer {session.token}"}

        if ref.startswith("mock://"):
            dest = await self._handle_mock(dest, item)
        elif ref.startswith(("http://", "https://")):
            dest = await self._download(dest, ref, auth_header)
            if dest.suffix.lower() == ".m3u8":
                dest = await self._remux_hls(dest, ref, auth_header)
        else:
            raise AppError("unsupported_media", "Media cannot be processed through the available authorized method.")

        if not dest.exists() or dest.stat().st_size == 0:
            raise AppError("processing_error", "Processing failed.")
        if dest.stat().st_size > self.cfg.max_upload_bytes:
            dest.unlink(missing_ok=True)
            raise AppError(
                "file_too_large",
                f"File too large for Telegram delivery ({human_size(dest.stat().st_size) if dest.exists() else '>limit'}).",
            )
        return dest

    # ------------------------------------------------------------ handlers

    async def _handle_mock(self, dest: Path, item: ContentItem) -> Path:
        if item.type == "pdf":
            return make_sample_pdf(dest.with_suffix(".pdf"), item.title)
        if item.type == "video":
            out = dest.with_suffix(".mp4")
            try:
                return await make_sample_video(out)
            except Exception:
                return make_sample_pdf(dest.with_suffix(".pdf"), item.title)
        return make_sample_pdf(dest.with_suffix(".pdf"), item.title)

    async def _download(self, dest: Path, url: str, auth_header: dict | None = None) -> Path:
        if not self._http:
            raise AppError("processing_error", "Media service not ready.")
        ext = self._ext_from_url(url)
        dest = dest.with_suffix(ext or ".bin")

        # size pre-check (HEAD)
        try:
            async with self._http.head(url, allow_redirects=True, headers=auth_header or {}) as resp:
                if resp.status >= 400:
                    raise self._http_error(resp.status)
                length = resp.headers.get("Content-Length")
                if length and int(length) > self.cfg.max_upload_bytes:
                    raise AppError("file_too_large", "File too large for Telegram delivery.")
                content_type = resp.headers.get("Content-Type", "")
                if "pdf" in content_type and ext not in (".pdf",):
                    dest = dest.with_suffix(".pdf")
        except AppError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("HEAD failed url=%s err=%s", safe_url(url), e.__class__.__name__)

        try:
            async with self._http.get(url, allow_redirects=True, headers=auth_header or {}) as resp:
                if resp.status >= 400:
                    raise self._http_error(resp.status)
                cd_name = _DISPOSITION_RE.search(resp.headers.get("Content-Disposition", ""))
                if cd_name:
                    dest = dest.with_name(secure_filename(cd_name.group(1)))
                downloaded = 0
                tmp = dest.with_suffix(dest.suffix + ".part")
                try:
                    with tmp.open("wb") as fh:
                        async for chunk in resp.content.iter_chunked(256 * 1024):
                            downloaded += len(chunk)
                            if downloaded > self.cfg.max_upload_bytes:
                                raise AppError("file_too_large", "File too large for Telegram delivery.")
                            fh.write(chunk)
                    tmp.replace(dest)
                except Exception:
                    tmp.unlink(missing_ok=True)
                    raise
                log.info(
                    "downloaded %s (%s)", safe_url(url), human_size(downloaded)
                )
                return dest
        except AppError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.warning("download failed url=%s err=%s", safe_url(url), e.__class__.__name__)
            raise AppError("network", "Temporary network error.")

    async def _remux_hls(self, dest: Path, url: str, auth_header: dict | None = None) -> Path:
        """HLS stream ko mp4 me remux (authorized, DRM-free streams only)."""
        if not shutil.which("ffmpeg"):
            raise AppError(
                "unsupported_media",
                "HLS processing requires ffmpeg (server par install karein).",
            )
        out = dest.with_suffix(".mp4")
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", url,
            "-c", "copy", "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            str(out),
        ]
        if auth_header:
            cmd += ["-headers", f"{next(iter(auth_header))}: {auth_header[next(iter(auth_header))]}\r\n"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=self.cfg.ffmpeg_timeout_sec)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            out.unlink(missing_ok=True)
            raise AppError("timeout", "Processing timeout.")
        if proc.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            out.unlink(missing_ok=True)
            raise AppError("processing_error", "Processing failed.")
        log.info("hls remux ok url=%s", safe_url(url))
        return out

    def _http_error(self, status: int) -> AppError:
        from utils.security import classify_http_error

        return classify_http_error(status)

    @staticmethod
    def _ext_from_url(url: str) -> str:
        path = url.split("?")[0].split("#")[0].rstrip("/")
        if "." not in path:
            return ".bin"
        ext = "." + path.rsplit(".", 1)[-1].lower()
        return ext if len(ext) <= 6 else ".bin"
