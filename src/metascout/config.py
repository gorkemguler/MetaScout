from __future__ import annotations

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse

DEFAULT_FILETYPES = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp"]

# Opt-in document *content* scan categories (ScanConfig.scan_content) — see
# content_scan/ package. Off by default: this reads inside each document's
# body text looking for PII, which is a materially different (and more
# invasive) thing than the always-on metadata-tag scan.
DEFAULT_CONTENT_CATEGORIES = ["tc_kimlik", "email_phone", "iban_card", "address_dob", "signature", "secrets", "infra"]

# Opt-in second discovery pass (ScanConfig.critical_files) — the same dork
# search/crawl/sitemap/wayback engines used for --filetypes, run again for
# plaintext/config-style files that tend to leak by simply existing and
# being indexed: an exposed .env, a debug .log, a forgotten .bak/.sql dump.
# Kept as a distinct list (and its own report section) rather than folded
# into --filetypes: "this file is publicly reachable" is itself the finding
# here, independent of whatever metadata extraction would find inside it
# (which is nothing, for a .txt file) — see pipeline.py and models.CriticalFile.
DEFAULT_CRITICAL_FILETYPES = ["txt", "log", "conf", "cfg", "ini", "env", "yml", "yaml", "sql", "bak"]

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
    # Independent of scan_content on purpose — the fast text/PII scan and
    # this slow (often 10s-130s per document, live-tested), experimental,
    # image-based check don't need each other. Also only takes effect if the
    # (heavy, unmaintained-upstream) signature-detect package +
    # ImageMagick/Ghostscript are installed. See content_scan/visual_signature.py
    # and the standalone `metascout visual-signature-scan` command, for
    # running this later against documents from a prior scan.
    visual_signature: bool = False
    # See DEFAULT_CRITICAL_FILETYPES above. Independent of scan_content: this
    # toggle controls whether the *discovery* pass runs at all; scan_content
    # additionally controls whether the found files' text also gets the
    # secrets/PII scan (same as any other document) once they're downloaded.
    critical_files: bool = False
    critical_file_types: list[str] = field(default_factory=lambda: list(DEFAULT_CRITICAL_FILETYPES))


def default_engines() -> list[str]:
    """crawl+sitemap+wayback+ddgs always (all free, no API key needed);
    auto-adds google/serper/brave once their API key is already configured
    on this machine (env var or .env) — shared by the CLI (`metascout scan`)
    and the REST API (`metascout api`) so both stay in sync with a single
    implementation instead of two copies that can silently drift apart.
    """
    engines = ["crawl", "sitemap", "wayback", "ddgs"]
    if os.environ.get("GOOGLE_API_KEY") and os.environ.get("GOOGLE_CSE_ID"):
        engines.append("google")
    if os.environ.get("SERPER_API_KEY"):
        engines.append("serper")
    if os.environ.get("BRAVE_API_KEY"):
        engines.append("brave")
    return engines


def hosts_of(urls: list[str]) -> list[str]:
    """Derives sorted, deduplicated hostnames from a list of full URLs —
    used to fill in `targets` automatically when only a manual URL list is
    given. Shared by the CLI and the REST API.
    """
    hosts = []
    for u in urls:
        host = urlparse(u).netloc
        if host:
            hosts.append(host)
    return sorted(set(hosts))
