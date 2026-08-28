from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_FILETYPES = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp"]

# Opt-in document *content* scan categories (ScanConfig.scan_content) — see
# content_scan/ package. Off by default: this reads inside each document's
# body text looking for PII, which is a materially different (and more
# invasive) thing than the always-on metadata-tag scan.
DEFAULT_CONTENT_CATEGORIES = ["tc_kimlik", "email_phone", "iban_card", "address_dob", "signature"]

# User-Agent identifies the tool honestly rather than spoofing a browser,
# so target site operators can see recon traffic in their logs and block it if unwanted.
DEFAULT_USER_AGENT = "MetaScout/0.1 (+authorized-metadata-recon-tool)"


@dataclass
class ScanConfig:
    targets: list[str]
    manual_urls: list[str] = field(default_factory=list)
    filetypes: list[str] = field(default_factory=lambda: list(DEFAULT_FILETYPES))
    engines: list[str] = field(default_factory=lambda: ["crawl", "sitemap"])
    max_docs: int = 50
    max_crawl_pages: int = 200
    max_crawl_depth: int = 3
    concurrency: int = 8
    request_timeout: int = 15
    max_download_bytes: int = 50 * 1024 * 1024
    output_dir: str = "./metascout_output"
    user_agent: str = DEFAULT_USER_AGENT
    respect_robots: bool = True
    include_subdomains: bool = False
    max_subdomains: int = 20
    google_api_key: str | None = None
    google_cse_id: str | None = None
    serper_api_key: str | None = None
    brave_api_key: str | None = None
    ddgs_backend: str = "auto"
    scan_content: bool = False
    content_categories: list[str] = field(default_factory=lambda: list(DEFAULT_CONTENT_CATEGORIES))
