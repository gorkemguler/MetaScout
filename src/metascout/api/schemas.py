from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..config import DEFAULT_CONTENT_CATEGORIES, DEFAULT_CRITICAL_FILETYPES, DEFAULT_FILETYPES


class ScanRequest(BaseModel):
    """Body for POST /v1/scans — mirrors `metascout scan`'s options. Discovers
    documents across `targets` (and/or `manual_urls`) and extracts/analyzes
    their metadata; every option below has the same meaning and default as
    its CLI counterpart, see the README's Full CLI reference."""

    targets: list[str] = Field(default_factory=list, description="Domains or base URLs to scan, e.g. [\"example.com\"]. Can be omitted if manual_urls is given — hostnames are then derived from those URLs automatically.")
    manual_urls: list[str] = Field(default_factory=list, description="Full document URLs to scan directly, skipping discovery for these (still downloaded, analyzed, and included in the report).")
    filetypes: list[str] = Field(default_factory=lambda: list(DEFAULT_FILETYPES), description="File extensions to look for.")
    engines: list[str] | None = Field(default=None, description="Subset of crawl,sitemap,wayback,ddgs,google,serper,brave. Defaults to crawl+sitemap+wayback+ddgs, plus google/serper/brave automatically if that engine's API key is configured on the server (env var/.env) — same auto-detection as the CLI.")
    ddgs_backend: str = Field(default="auto", description="Backend(s) for the 'ddgs' engine, e.g. 'duckduckgo', 'google', 'bing', or a comma-separated list.")
    max_docs: int = Field(default=50, ge=1, description="Maximum documents to download and analyze across all targets.")
    max_crawl_pages: int = Field(default=200, ge=1)
    max_crawl_depth: int = Field(default=3, ge=0)
    concurrency: int = Field(default=8, ge=1, le=64)
    timeout: int = Field(default=15, ge=1, description="Per-request timeout in seconds.")
    max_download_mb: int = Field(default=50, ge=1)
    subdomains: bool = Field(default=False, description="Enumerate subdomains via crt.sh (Certificate Transparency logs) and scan each one too.")
    max_subdomains: int = Field(default=20, ge=1)
    ignore_robots: bool = Field(default=False, description="Ignore robots.txt during crawling — only with explicit authorization.")
    scan_content: bool = Field(default=False, description="Also scan document body text for PII/secrets/infra leaks (heuristic).")
    content_categories: list[str] = Field(default_factory=lambda: list(DEFAULT_CONTENT_CATEGORIES), description="Subset of tc_kimlik,email_phone,iban_card,address_dob,signature,secrets,infra. Only used with scan_content.")
    visual_signature: bool = Field(default=False, description="EXPERIMENTAL: slow, heuristic, image-based handwritten-signature detection.")
    critical_files: bool = Field(default=False, description="Also run a second discovery pass for plaintext/config-style 'critical' files (see critical_file_types).")
    critical_file_types: list[str] = Field(default_factory=lambda: list(DEFAULT_CRITICAL_FILETYPES), description="File extensions for critical_files.")
    report_lang: Literal["en", "tr"] = Field(default="en", description="HTML report language.")

    @model_validator(mode="after")
    def _require_a_target(self) -> "ScanRequest":
        if not self.targets and not self.manual_urls:
            raise ValueError("Provide at least one of 'targets' or 'manual_urls'.")
        return self


class LocalScanRequest(BaseModel):
    """Body for POST /v1/local-scans — mirrors `metascout local-scan`.
    Analyzes documents the server already has (a directory it can read) or
    downloads a fixed URL list directly; no discovery either way. Provide
    exactly one of `directory` or `urls`."""

    directory: str | None = Field(default=None, description="Absolute path readable by the account running `metascout api`, searched recursively. Mutually exclusive with urls.")
    urls: list[str] = Field(default_factory=list, description="Full document URLs to download and analyze directly, no discovery. Mutually exclusive with directory.")
    filetypes: list[str] = Field(default_factory=lambda: list(DEFAULT_FILETYPES))
    scan_content: bool = False
    content_categories: list[str] = Field(default_factory=lambda: list(DEFAULT_CONTENT_CATEGORIES))
    visual_signature: bool = False
    critical_files: bool = False
    critical_file_types: list[str] = Field(default_factory=lambda: list(DEFAULT_CRITICAL_FILETYPES))
    report_lang: Literal["en", "tr"] = "en"

    @model_validator(mode="after")
    def _exactly_one_source(self) -> "LocalScanRequest":
        has_dir = bool(self.directory)
        has_urls = bool(self.urls)
        if has_dir == has_urls:  # both False, or both True
            raise ValueError("Provide exactly one of 'directory' or 'urls', not both/neither.")
        return self


class JobCreated(BaseModel):
    job_id: str
    status: Literal["queued"]
    run_id: str
    created_at: datetime
    links: dict[str, str]


class JobSummary(BaseModel):
    documents_discovered: int
    documents_with_metadata: int
    findings_total: int
    content_findings: int
    critical_files: int


class JobStatusResponse(BaseModel):
    job_id: str
    kind: Literal["scan", "local-scan"]
    status: Literal["queued", "running", "done", "error"]
    run_id: str
    targets: list[str]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    summary: JobSummary | None
    links: dict[str, str]


class JobLogResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    lines: list[str]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    active_jobs: int
