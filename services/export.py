"""
TXT export service — PRD sections 10-12, 34-35.

- Complete course / videos only / PDFs only / selected chapters
- Multiple courses: EXPORT_MODE single (1 file) ya separate (per course)
- Reference mode: TXT_REFERENCE_MODE=base (host+path, PRD-safe default)
  ya full (platform-provided signed URL bhi — personal authorized use)
- Streaming write (large courses ke liye memory-safe)
- Temporary file → upload → delete (caller)
- TXT me kabhi password/session secrets nahi hote (sirf metadata + references)
"""
from __future__ import annotations

import re
from pathlib import Path

from platforms.models import ContentItem, ContentTree, Course, SessionData
from services.content import ContentService
from services.courses import CourseService

from utils.logger import get_logger
from utils.security import AppError, safe_slug

log = get_logger("export")


class ExportService:
    def __init__(self, courses: CourseService, content: ContentService, export_dir: str,
                 export_mode: str = "single", reference_mode: str = "base"):
        self.courses_svc = courses
        self.content_svc = content
        self.export_dir = Path(export_dir)
        self.export_mode = export_mode
        self.reference_mode = reference_mode  # base | full

    # ------------------------------------------------------------ reference

    def sanitize_reference(self, reference: str) -> str:
        """TXT me jane wale reference ko mode ke hisaab se banata hai.

        base: sirf scheme+host+path (signed query params hatao — PRD §10).
              Link ek identifier/reference ki tarah kaam karti hai.
        full: platform-provided complete reference — signed URL bhi included.
              NOTE: full mode me links account-owner ke personal authorized
              use ke liye hain aur platform ke hisaab se expire ho sakti hain.
        """
        if not reference or reference.startswith("mock://"):
            return reference
        try:
            from urllib.parse import urlsplit, urlunsplit

            parts = urlsplit(reference)
            if self.reference_mode == "full":
                return reference
            return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        except Exception:
            return re.sub(r"[?&#].*$", "", reference)

    # ------------------------------------------------------------ selection

    def filter_items(self, tree: ContentTree, kind: str, chapter_idx: set[int] | None = None) -> list[ContentItem]:
        """kind: complete | videos | pdfs; chapter_idx: set of chapter indexes."""
        items: list[ContentItem] = []
        for idx, ch in enumerate(tree.chapters):
            if chapter_idx is not None and idx not in chapter_idx:
                continue
            for it in ch.items:
                if kind == "videos" and it.type != "video":
                    continue
                if kind == "pdfs" and it.type != "pdf":
                    continue
                items.append(it)
        return items

    # ------------------------------------------------------------ generation

    def _write_header(self, fh) -> None:
        fh.write("APPX COURSE\n")
        fh.write("============\n\n")
        if self.reference_mode == "full":
            fh.write(
                "Note: Is export me platform-provided complete references (signed\n"
                "URLs) hain. Ye sirf account-owner ke personal authorized use ke\n"
                "liye hain — links expire ho sakti hain.\n\n"
            )

    def _write_course(self, fh, course_title: str, tree: ContentTree, items_by_chapter: dict[str, list[ContentItem]]) -> None:
        self._write_header(fh)
        fh.write(f"Course: {course_title}\n\n")
        for ch in tree.chapters:
            items = items_by_chapter.get(ch.title, [])
            if not items:
                continue
            fh.write(f"{ch.title}\n")
            fh.write("-" * len(ch.title) + "\n\n")
            for i, it in enumerate(items, start=1):
                fh.write(f"{it.type.upper()} {i:02d}\n")
                fh.write(f"Title: {it.title}\n")
                fh.write(f"Type: {it.type}\n")
                if it.reference:
                    # signed query params TXT me nahi jate (PRD §10)
                    fh.write(f"Authorized reference: {self.sanitize_reference(it.reference)}\n")
                fh.write("\n")

    async def generate(
        self,
        session: SessionData,
        tg_id: int,
        courses: list[Course],
        kind: str = "complete",
        chapter_idx: set[int] | None = None,
        export_id: str = "EXP",
    ) -> list[Path]:
        """Files generate karta hai; caller upload ke baad delete karega."""
        if not courses:
            raise AppError("invalid_input", "No courses selected.")

        out_dir = self.export_dir / export_id
        out_dir.mkdir(parents=True, exist_ok=True)

        trees: list[tuple[Course, ContentTree]] = []
        for course in courses:
            tree = await self.content_svc.get_tree(session, tg_id, course)
            trees.append((course, tree))

        files: list[Path] = []
        if self.export_mode == "separate":
            for course, tree in trees:
                path = out_dir / f"{safe_slug(course.title)}_course.txt"
                items_by_chapter = self._group_by_chapter(tree, kind, chapter_idx)
                with path.open("w", encoding="utf-8") as fh:
                    self._write_course(fh, course.title, tree, items_by_chapter)
                files.append(path)
        else:
            path = out_dir / "appx_course_export.txt"
            with path.open("w", encoding="utf-8") as fh:
                for course, tree in trees:
                    items_by_chapter = self._group_by_chapter(tree, kind, chapter_idx)
                    self._write_course(fh, course.title, tree, items_by_chapter)
                    if len(trees) > 1:
                        fh.write("\n" + "=" * 40 + "\n\n")
            files.append(path)
        return files

    def _group_by_chapter(self, tree: ContentTree, kind: str, chapter_idx: set[int] | None) -> dict[str, list[ContentItem]]:
        result: dict[str, list[ContentItem]] = {}
        for idx, ch in enumerate(tree.chapters):
            if chapter_idx is not None and idx not in chapter_idx:
                continue
            items = [it for it in ch.items if self._keep(it, kind)]
            if items:
                result[ch.title] = items
        return result

    @staticmethod
    def _keep(it: ContentItem, kind: str) -> bool:
        if kind == "videos":
            return it.type == "video"
        if kind == "pdfs":
            return it.type == "pdf"
        return True

    # ------------------------------------------------------------ cleanup

    def delete_export(self, export_id: str) -> None:
        path = self.export_dir / export_id
        if path.exists():
            for f in path.iterdir():
                try:
                    f.unlink()
                except OSError:
                    pass
            try:
                path.rmdir()
            except OSError:
                pass
