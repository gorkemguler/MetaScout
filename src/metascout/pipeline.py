from __future__ import annotations

import os
from typing import Callable
from urllib.parse import urlparse

from .config import ScanConfig
from .discovery import brave_dork_search, crawl_site, ddgs_dork_search, find_subdomains, google_dork_search, serper_dork_search, sitemap_search, wayback_search
from .downloader import download_documents
from .metadata import exiftool_available, extract_metadata
from .metadata.analyzer import analyze
from .models import DiscoveredDocument, DiscoverySource, ScanFindings

LogFn = Callable[[str], None]


def _noop_log(message: str) -> None:
    pass


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


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
            elif engine == "wayback":
                docs = wayback_search(
                    host, cfg.filetypes,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                    max_results=max(cfg.max_docs, 100),
                )
            elif engine == "google":
                # Google's API itself caps at ~100 results/query (start<=91),
                # so there's no point asking for more than that per filetype.
                docs = google_dork_search(
                    host, cfg.filetypes,
                    api_key=cfg.google_api_key, cse_id=cfg.google_cse_id,
                    timeout=cfg.request_timeout, max_results_per_type=min(cfg.max_docs, 100),
                )
            elif engine == "serper":
                # Unlike Google's own API, Serper isn't hard-capped at ~100 —
                # it paginates real Google SERP pages, so let --max-docs be
                # the real ceiling; pagination self-terminates once the
                # underlying results actually run out.
                docs = serper_dork_search(
                    host, cfg.filetypes,
                    api_key=cfg.serper_api_key, timeout=cfg.request_timeout,
                    max_results_per_type=cfg.max_docs,
                )
            elif engine == "brave":
                docs = brave_dork_search(
                    host, cfg.filetypes,
                    api_key=cfg.brave_api_key, timeout=cfg.request_timeout,
                    max_results_per_type=cfg.max_docs,
                )
            elif engine == "ddgs":
                docs = ddgs_dork_search(
                    host, cfg.filetypes,
                    timeout=cfg.request_timeout, backend=cfg.ddgs_backend,
                    max_results_per_type=cfg.max_docs,
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
    if "google" in cfg.engines:
        log(
            "! google: Google, Custom Search JSON API'yi 1 Ocak 2027'de kapatıyor ve "
            "yeni Google Cloud projelerini şimdiden reddediyor (PERMISSION_DENIED). "
            "Sorun yaşarsanız 'serper' motorunu deneyin (SERPER_API_KEY, https://serper.dev)."
        )

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

    if cfg.manual_urls:
        log(f"adding {len(cfg.manual_urls)} manually provided URL(s) ...")
        existing_urls = {d.url for d in discovered}
        added = 0
        for url in cfg.manual_urls:
            if url not in existing_urls:
                discovered.append(DiscoveredDocument(url=url, source=DiscoverySource.MANUAL, filetype=_ext_of(url)))
                existing_urls.add(url)
                added += 1
        log(f"  {added} new, {len(cfg.manual_urls) - added} already discovered")

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
