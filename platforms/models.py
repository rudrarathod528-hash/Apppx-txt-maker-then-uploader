"""Normalized data models — platform responses in in one standard shape."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Tenant:
    name: str
    api_base: str

    @property
    def host(self) -> str:
        try:
            return self.api_base.split("//")[1].split("/")[0]
        except IndexError:
            return self.api_base


@dataclass
class SessionData:
    token: str
    user_id: str = ""
    tenant_id: str = ""
    tenant_name: str = ""
    name: str = ""
    expiry: int = 0  # epoch seconds; 0 = unknown
    refresh_token: str = ""

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "name": self.name,
            "expiry": self.expiry,
            "refresh_token": self.refresh_token,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionData":
        return cls(**{k: data.get(k, "") for k in (
            "token", "user_id", "tenant_id", "tenant_name", "name", "expiry", "refresh_token"
        )})


@dataclass
class Course:
    course_id: str
    title: str
    meta: dict = field(default_factory=dict)  # videos/pdfs/chapters counts etc.


@dataclass
class ContentItem:
    content_id: str
    title: str
    type: str  # video | pdf | other
    chapter: str = ""
    reference: str = ""  # authorized platform-provided reference (URL / mock://)
    meta: dict = field(default_factory=dict)


@dataclass
class Chapter:
    title: str
    items: list[ContentItem] = field(default_factory=list)

    @property
    def videos(self) -> int:
        return sum(1 for i in self.items if i.type == "video")

    @property
    def pdfs(self) -> int:
        return sum(1 for i in self.items if i.type == "pdf")


@dataclass
class ContentTree:
    course_id: str
    course_title: str
    chapters: list[Chapter] = field(default_factory=list)

    def flatten(self) -> list[ContentItem]:
        out: list[ContentItem] = []
        for ch in self.chapters:
            out.extend(ch.items)
        return out

    def counts(self) -> dict:
        items = self.flatten()
        return {
            "videos": sum(1 for i in items if i.type == "video"),
            "pdfs": sum(1 for i in items if i.type == "pdf"),
            "others": sum(1 for i in items if i.type == "other"),
            "items": len(items),
            "chapters": len(self.chapters),
        }
