"""
Mock platform — PLATFORM_MODE=mock ke liye.

Bina real credentials ke pura flow test karne deta hai:
    institute : "Demo Institute"
    username  : demo
    password  : demo123

Sample courses + chapters + items generate karta hai; media items
`mock://` reference dete hain jise MediaService sample files me convert
karta hai (TXT/PDF/MP4).
"""
from __future__ import annotations

import asyncio
import shutil
import time
from pathlib import Path

from platforms.models import Chapter, ContentItem, ContentTree, Course, SessionData
from utils.security import AppError

DEMO_TENANT_NAME = "Demo Institute"
DEMO_TENANT_ID = "demo-tenant"
DEMO_USER = "demo"
DEMO_PASS = "demo123"

COURSES = [
    ("PHY", "Physics"),
    ("MAT", "Mathematics"),
    ("CHE", "Chemistry"),
    ("ENG", "English"),
]

CHAPTERS_PER_COURSE = 3
ITEMS_PER_CHAPTER = 3  # 2 videos + 1 pdf


def _item_type(i: int) -> str:
    return "video" if i % 3 != 2 else "pdf"


def _item_title(course: str, ch: int, i: int) -> str:
    kind = "Video" if _item_type(i) == "video" else "PDF"
    topics = {
        "Physics": ["Motion", "Force", "Notes"],
        "Mathematics": ["Algebra", "Calculus", "Notes"],
        "Chemistry": ["Atomic Structure", "Bonding", "Notes"],
        "English": ["Grammar", "Comprehension", "Notes"],
    }
    base = topics.get(course, ["Topic A", "Topic B", "Notes"])[i % 3]
    return f"{kind} {ch}.{i + 1} — {base}"


class MockPlatform:
    """Deterministic demo backend. Passwords kabhi store nahi hote."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}  # token -> payload

    async def login(self, tenant_id: str, tenant_name: str, username: str, password: str) -> SessionData:
        await asyncio.sleep(0.1)  # simulate latency
        if username != DEMO_USER or password != DEMO_PASS:
            raise AppError("invalid_login", "Login failed. Please check your ID/password.")
        token = "mock-token-" + str(int(time.time() * 1000))
        self.sessions[token] = {"user_id": "demo-user-1", "name": "Demo User"}
        if not tenant_id or tenant_id.startswith("mock://"):
            tenant_id = DEMO_TENANT_ID
        return SessionData(
            token=token,
            user_id="demo-user-1",
            tenant_id=tenant_id,
            tenant_name=tenant_name or DEMO_TENANT_NAME,
            name="Demo User",
            expiry=int(time.time()) + 86400,
        )

    async def revoke(self, token: str) -> None:
        self.sessions.pop(token, None)

    async def refresh(self, token: str) -> SessionData:
        payload = self.sessions.get(token)
        if not payload:
            raise AppError("unauthorized", "Session expired.")
        return SessionData(
            token=token,
            user_id=payload["user_id"],
            name=payload["name"],
            tenant_id=DEMO_TENANT_ID,
            tenant_name=DEMO_TENANT_NAME,
            expiry=int(time.time()) + 86400,
        )

    async def courses(self, token: str) -> list[Course]:
        await asyncio.sleep(0.1)
        if token not in self.sessions:
            raise AppError("unauthorized", "Session expired.")
        return [
            Course(
                course_id=cid,
                title=title,
                meta={
                    "videos": CHAPTERS_PER_COURSE * ITEMS_PER_CHAPTER // 3 * 2,
                    "pdfs": CHAPTERS_PER_COURSE * ITEMS_PER_CHAPTER // 3,
                    "chapters": CHAPTERS_PER_COURSE,
                },
            )
            for cid, title in COURSES
        ]

    async def content(self, token: str, course_id: str) -> ContentTree:
        await asyncio.sleep(0.1)
        if token not in self.sessions:
            raise AppError("unauthorized", "Session expired.")
        course_title = dict(COURSES).get(course_id, "Unknown Course")
        chapters: list[Chapter] = []
        for ch in range(1, CHAPTERS_PER_COURSE + 1):
            items: list[ContentItem] = []
            for i in range(ITEMS_PER_CHAPTER):
                items.append(
                    ContentItem(
                        content_id=f"{course_id}-c{ch}-i{i + 1}",
                        title=_item_title(course_title, ch, i),
                        type=_item_type(i),
                        chapter=f"Chapter {ch:02d}",
                        reference=f"mock://{course_id.lower()}/{ch}/{i + 1}",
                    )
                )
            chapters.append(Chapter(title=f"Chapter {ch:02d}", items=items))
        return ContentTree(course_id=course_id, course_title=course_title, chapters=chapters)


# ------------------------------------------------------------ sample media

def make_sample_pdf(path: Path, title: str) -> Path:
    """Chhota but valid PDF file generate karta hai."""
    content = f"APPX Course Bot - sample PDF\n\n{title}\n\nThis is authorized demo content."
    lines = []
    offset = 0
    objects = []
    objects.append("<< /Type /Catalog /Pages 2 0 R >>")
    objects.append("<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
    )
    stream = "BT /F1 18 Tf 72 720 Td (%s) Tj ET BT /F1 12 Tf 72 690 Td (%s) Tj ET" % (
        _pdf_escape(title)[:200], _pdf_escape(content)[:2000]
    )
    objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    body = []
    for i, obj in enumerate(objects, start=1):
        body.append(f"{i} 0 obj\n{obj}\nendobj")
    xref_pos = 0
    out = ["%PDF-1.4"]
    offsets = [0]
    for b in body:
        offsets.append(len("\n".join(out)) + 1)
        out.append(b)
    xref_pos = len("\n".join(out))
    xref = [f"xref\n0 {len(objects) + 1}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    )
    # PDF text WinAnsi (latin-1) me hota hai — non-latin1 chars replace karo
    path.write_bytes(("\n".join(out) + "\n" + "".join(xref) + trailer).encode("latin-1", errors="replace"))
    return path


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\n", " ")


async def make_sample_video(path: Path) -> Path:
    """Tiny mp4 banane ki koshish karta hai (ffmpeg), warna text sample."""
    if shutil.which("ffmpeg"):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if path.exists() and path.stat().st_size > 0:
            return path
        # fallback codec (libx264 nahi hai to mpeg4)
        cmd[cmd.index("libx264")] = "mpeg4"
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            await asyncio.wait_for(proc.wait(), timeout=30)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if path.exists() and path.stat().st_size > 0:
            return path
    # ffmpeg nahi hai — honest text sample
    path.write_text(
        "APPX Course Bot — sample video file (demo mode).\n"
        "ffmpeg install karne par real tiny MP4 generate hoga.\n",
        encoding="utf-8",
    )
    return path
