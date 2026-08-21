from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DiscoverySource(str, Enum):
    GOOGLE = "google"
    BRAVE = "brave"
    CRAWL = "crawl"
    SITEMAP = "sitemap"


@dataclass(frozen=True)
class DiscoveredDocument:
    url: str
    source: DiscoverySource
    filetype: str


@dataclass
class DownloadedDocument:
    url: str
    local_path: str
    filetype: str
    source: DiscoverySource
    sha256: str = ""
    size_bytes: int = 0
    error: str | None = None


@dataclass
class DocumentMetadata:
    url: str
    local_path: str
    filetype: str
    raw: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class Finding:
    value: str
    document_urls: list[str] = field(default_factory=list)
    field_name: str = ""


@dataclass
class ScanFindings:
    targets: list[str]
    scanned_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    documents: list[DocumentMetadata] = field(default_factory=list)
    documents_by_target: dict[str, int] = field(default_factory=dict)
    usernames: dict[str, Finding] = field(default_factory=dict)
    emails: dict[str, Finding] = field(default_factory=dict)
    software: dict[str, Finding] = field(default_factory=dict)
    operating_systems: dict[str, Finding] = field(default_factory=dict)
    internal_paths: dict[str, Finding] = field(default_factory=dict)
    servers_and_printers: dict[str, Finding] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def documents_with_metadata(self) -> int:
        return sum(1 for d in self.documents if d.raw and not d.error)
