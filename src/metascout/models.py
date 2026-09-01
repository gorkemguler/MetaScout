from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class DiscoverySource(str, Enum):
    GOOGLE = "google"
    SERPER = "serper"
    BRAVE = "brave"
    CRAWL = "crawl"
    SITEMAP = "sitemap"
    WAYBACK = "wayback"
    DDGS = "ddgs"
    MANUAL = "manual"


@dataclass(frozen=True)
class DiscoveredDocument:
    url: str
    source: DiscoverySource
    filetype: str
    # Fallback download location when `url` itself is unreachable (e.g. a
    # Wayback Machine snapshot for a file removed from the live site).
    # `url` stays the canonical original — used for cross-engine dedup and
    # in the report — regardless of which one the bytes actually came from.
    archive_url: str | None = None


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
class ContentFinding:
    """One hit from the opt-in document *content* scan (ScanConfig.scan_content)
    — scans a document's body text, unlike Finding/metadata analysis which
    only looks at exiftool metadata tags. This is a heuristic scanner, not a
    certified DLP tool: every hit needs manual verification, not blind trust.

    `masked_value` never carries the raw sensitive value for the more
    critical categories (tc_kimlik/iban/credit_card) — it's redacted at
    detection time so a report itself never becomes a store of raw PII.
    """
    document_url: str
    category: str  # tc_kimlik | email | phone | iban | credit_card | dob | address | signature
    masked_value: str
    context: str = ""


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
    # GPS coordinates from embedded photos (e.g. a phone photo pasted into a
    # Word doc) — a classic FOCA-style finding: metadata leaking someone's
    # physical location, not just software/username info.
    geolocation: dict[str, Finding] = field(default_factory=dict)
    content_findings: list[ContentFinding] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def documents_with_metadata(self) -> int:
        return sum(1 for d in self.documents if d.raw and not d.error)

    @property
    def content_findings_by_category(self) -> dict[str, list[ContentFinding]]:
        grouped: dict[str, list[ContentFinding]] = {}
        for f in self.content_findings:
            grouped.setdefault(f.category, []).append(f)
        return grouped
