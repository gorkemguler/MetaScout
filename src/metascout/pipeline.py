from __future__ import annotations

import os
from typing import Callable

from .config import ScanConfig
from .discovery import brave_dork_search, crawl_site, find_subdomains, google_dork_search, sitemap_search
from .downloader import download_documents
from .metadata import exiftool_available, extract_metadata
from .metadata.analyzer import analyze
from .models import DiscoveredDocument, ScanFindings

LogFn = Callable[[str], None]


def _noop_log(message: str) -> None:
    pass


def _run_discovery_for_host(host: str, cfg: ScanConfig, log: LogFn) -> list[DiscoveredDocument]:
    found: dict[str, DiscoveredDocument] = {}

    for engine in cfg.engines:
        try:
            if engine == "crawl":
                docs = crawl_site(
                    host, cfg.filetypes,
                    max_pages=cfg.max_crawl_pages, max_depth=cfg.max_crawl_depth,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                    respect_robots=cfg.respect_robots,
                )
            elif engine == "sitemap":
                docs = sitemap_search(
                    host, cfg.filetypes,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                )
            elif engine == "google":
                docs = google_dork_search(
                    host, cfg.filetypes,
                    api_key=cfg.google_api_key, cse_id=cfg.google_cse_id,
                    timeout=cfg.request_timeout,
                )
            elif engine == "brave":
                docs = brave_dork_search(
                    host, cfg.filetypes,
                    api_key=cfg.brave_api_key, timeout=cfg.request_timeout,
                )
            else:
                log(f"! unknown engine '{engine}', skipping")
                continue
        except (ValueError, RuntimeError) as exc:
            log(f"! {engine} skipped for {host}: {exc}")
            continue

        for d in docs:
            found.setdefault(d.url, d)

    return list(found.values())


def discover_all(cfg: ScanConfig, log: LogFn = _noop_log) -> list[DiscoveredDocument]:
    found: dict[str, DiscoveredDocument] = {}

    for target in cfg.targets:
        hosts = [target]

        if cfg.include_subdomains:
            log(f"enumerating subdomains for {target} via crt.sh ...")
            subs = find_subdomains(target, timeout=cfg.request_timeout, user_agent=cfg.user_agent)
            log(f"found {len(subs)} subdomain(s) for {target}")
            if len(subs) > cfg.max_subdomains:
                log(f"capping to --max-subdomains={cfg.max_subdomains}")
                subs = subs[: cfg.max_subdomains]
            hosts += subs

        for host in hosts:
            log(f"discovery on {host} via {', '.join(cfg.engines)} ...")
            docs = _run_discovery_for_host(host, cfg, log)
            log(f"  found {len(docs)} link(s) on {host}")
            for d in docs:
                found.setdefault(d.url, d)

    return list(found.values())


def run_scan(cfg: ScanConfig, log: LogFn = _noop_log) -> ScanFindings:
    """Runs the full discover -> download -> extract -> analyze pipeline.

    Shared by the CLI (`metascout scan`) and the local web UI (`metascout web`)
    so both stay in sync with a single implementation.
    """
    if not exiftool_available():
        raise RuntimeError(
            "exiftool not found on PATH. Install it first, e.g. "
            "`brew install exiftool` (macOS) or `apt install libimage-exiftool-perl` (Debian/Ubuntu)."
        )

    discovered = discover_all(cfg, log)
    if not discovered:
        log("No documents discovered. Nothing to analyze.")
        return analyze([], targets=cfg.targets)

    if len(discovered) > cfg.max_docs:
        log(f"Capping {len(discovered)} discovered documents to max_docs={cfg.max_docs}")
        discovered = discovered[: cfg.max_docs]

    os.makedirs(cfg.output_dir, exist_ok=True)
    downloads_dir = os.path.join(cfg.output_dir, "downloads")

    log(f"downloading {len(discovered)} document(s) ...")
    downloaded = download_documents(
        discovered, dest_dir=downloads_dir, concurrency=cfg.concurrency,
        timeout=cfg.request_timeout, max_bytes=cfg.max_download_bytes, user_agent=cfg.user_agent,
    )
    ok_count = sum(1 for d in downloaded if not d.error)
    log(f"{ok_count}/{len(downloaded)} downloaded successfully")

    log("extracting metadata with exiftool ...")
    doc_metadata = extract_metadata(downloaded)

    log("analyzing metadata ...")
    findings = analyze(doc_metadata, targets=cfg.targets)

    return findings
