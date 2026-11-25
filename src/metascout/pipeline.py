from __future__ import annotations

import os
from dataclasses import replace
from typing import Callable
from urllib.parse import urlparse

from .config import ScanConfig
from .content_scan import (
    detect_visual_signature, missing_dependencies, missing_visual_signature_dependencies, scan_document,
)
from .discovery import brave_dork_search, commoncrawl_search, crawl_site, ddgs_dork_search, find_subdomains, google_dork_search, serper_dork_search, sitemap_search, wayback_search
from .downloader import download_documents
from .metadata import exiftool_available, extract_metadata
from .metadata.analyzer import analyze
from .models import ContentFinding, CriticalFile, DiscoveredDocument, DiscoverySource, DownloadedDocument, ScanFindings

LogFn = Callable[[str], None]


def _noop_log(message: str) -> None:
    pass


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _run_discovery_for_host(host: str, cfg: ScanConfig, filetypes: list[str], log: LogFn,
                            pages: dict | None = None) -> list[DiscoveredDocument]:
    found: dict[str, DiscoveredDocument] = {}

    for engine in cfg.engines:
        try:
            if engine == "crawl":
                docs = crawl_site(
                    host, filetypes,
                    max_pages=cfg.max_crawl_pages, max_depth=cfg.max_crawl_depth,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                    respect_robots=cfg.respect_robots, page_cache=pages,
                )
            elif engine == "sitemap":
                docs = sitemap_search(
                    host, filetypes,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                )
            elif engine == "wayback":
                docs = wayback_search(
                    host, filetypes,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                    max_results=max(cfg.max_docs, 100),
                )
            elif engine == "commoncrawl":
                docs = commoncrawl_search(
                    host, filetypes,
                    timeout=cfg.request_timeout, user_agent=cfg.user_agent,
                    max_results=max(cfg.max_docs, 100),
                )
            elif engine == "google":
                # Google's API itself caps at ~100 results/query (start<=91),
                # so there's no point asking for more than that per filetype.
                docs = google_dork_search(
                    host, filetypes,
                    api_key=cfg.google_api_key, cse_id=cfg.google_cse_id,
                    timeout=cfg.request_timeout, max_results_per_type=min(cfg.max_docs, 100),
                )
            elif engine == "serper":
                # Unlike Google's own API, Serper isn't hard-capped at ~100 —
                # it paginates real Google SERP pages, so let --max-docs be
                # the real ceiling; pagination self-terminates once the
                # underlying results actually run out.
                docs = serper_dork_search(
                    host, filetypes,
                    api_key=cfg.serper_api_key, timeout=cfg.request_timeout,
                    max_results_per_type=cfg.max_docs,
                )
            elif engine == "brave":
                docs = brave_dork_search(
                    host, filetypes,
                    api_key=cfg.brave_api_key, timeout=cfg.request_timeout,
                    max_results_per_type=cfg.max_docs,
                )
            elif engine == "ddgs":
                docs = ddgs_dork_search(
                    host, filetypes,
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


def discover_all(cfg: ScanConfig, log: LogFn = _noop_log, *, filetypes: list[str] | None = None,
                 cache: dict | None = None) -> list[DiscoveredDocument]:
    """Runs discovery across all targets/subdomains via cfg.engines.

    `filetypes` defaults to cfg.filetypes (the normal document search); pass
    cfg.critical_file_types instead to run the same discovery engines for
    the opt-in "critical files" pass (see ScanConfig.critical_files) without
    duplicating the target/subdomain-enumeration loop below.

    A scan runs this once per kind of file it looks for. Give every one of
    those calls the same `cache` dict and the later ones reuse the crawled
    pages and subdomain lists of the first instead of fetching them again.
    """
    filetypes = cfg.filetypes if filetypes is None else filetypes
    cache = {} if cache is None else cache
    pages = cache.setdefault("pages", {})
    subdomains = cache.setdefault("subdomains", {})

    if "google" in cfg.engines:
        log(
            "! google: Google, Custom Search JSON API'yi 1 Ocak 2027'de kapatıyor ve "
            "yeni Google Cloud projelerini şimdiden reddediyor (PERMISSION_DENIED). "
            "Sorun yaşarsanız 'serper' motorunu (SERPER_API_KEY, https://serper.dev) ya da "
            "hiç anahtar gerektirmeyen '--engines ddgs --ddgs-backend google'ı deneyin."
        )

    found: dict[str, DiscoveredDocument] = {}

    for target in cfg.targets:
        hosts = [target]

        if cfg.include_subdomains:
            if target not in subdomains:
                log(f"enumerating subdomains for {target} via crt.sh ...")
                subdomains[target] = find_subdomains(target, timeout=cfg.request_timeout, user_agent=cfg.user_agent)
            subs = subdomains[target]
            log(f"found {len(subs)} subdomain(s) for {target}")
            if len(subs) > cfg.max_subdomains:
                log(f"capping to --max-subdomains={cfg.max_subdomains}")
                subs = subs[: cfg.max_subdomains]
            hosts += subs

        for host in hosts:
            log(f"discovery on {host} via {', '.join(cfg.engines)} ...")
            docs = _run_discovery_for_host(host, cfg, filetypes, log, pages)
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

    # Pages crawled and subdomains found, shared by every discovery pass below.
    cache: dict = {}
    discovered = discover_all(cfg, log, cache=cache)

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

    doc_metadata: list = []
    if not discovered:
        log("No documents discovered. Nothing to analyze.")
    else:
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

    # Independent of the document search, like the critical files below: a
    # site with no documents at all can still have a geotagged photo on it.
    pictures: list = []
    images_scanned = 0
    if cfg.images:
        pictures, images_scanned = _read_images(cfg, log, cache, skip_urls={d.url for d in discovered})

    if doc_metadata or pictures:
        log("analyzing metadata ...")
    findings = analyze(doc_metadata + pictures, targets=cfg.targets)
    findings.images_scanned = images_scanned

    # Independent of the main document search on purpose (see
    # ScanConfig.critical_files / DEFAULT_CRITICAL_FILETYPES): runs even if
    # the main pass above found nothing, since someone may only care about
    # exposed .env/.log/.sql-style files, not pdf/doc/... documents.
    critical_downloaded: list = []
    if cfg.critical_files:
        critical_downloaded = _discover_and_download_critical_files(cfg, log, cache)
    findings.critical_files = [
        CriticalFile(url=d.url, filetype=d.filetype, source=d.source, size_bytes=d.size_bytes, error=d.error)
        for d in critical_downloaded
    ]

    content_hits: list[ContentFinding] = []
    # Independent switches on purpose: the fast text/PII scan (--scan-content)
    # and the slow, experimental visual signature check (--visual-signature)
    # don't need each other — run whichever one(s) were actually asked for.
    if cfg.scan_content:
        content_hits.extend(_scan_content(doc_metadata, cfg.content_categories, log))
        if critical_downloaded:
            # Same scan, same categories — a leaked .env/.conf is exactly
            # where a real secret/internal-host hit is most likely to show up.
            content_hits.extend(_scan_content(critical_downloaded, cfg.content_categories, log))
    if cfg.visual_signature:
        content_hits.extend(scan_visual_signatures(doc_metadata, log))
    findings.content_findings = content_hits

    return findings


# Plaintext files every site publishes on purpose — crawler, security-contact,
# ad-seller and AI-crawler conventions. They match the critical file types but
# being public is their whole point, so they are never a finding.
_PUBLIC_BY_DESIGN = {
    "robots.txt", "security.txt", "humans.txt", "ads.txt", "app-ads.txt", "llms.txt", "llms-full.txt",
    "dnt-policy.txt", "trust.txt", "sitemap.txt", "sitemap.xml",
}


def _public_by_design(url: str) -> bool:
    return urlparse(url).path.rsplit("/", 1)[-1].lower() in _PUBLIC_BY_DESIGN


def _discover_and_download_critical_files(cfg: ScanConfig, log: LogFn, cache: dict | None = None) -> list[DownloadedDocument]:
    """Second, independent discovery pass for plaintext/config-style
    "critical" files (see ScanConfig.critical_files / DEFAULT_CRITICAL_FILETYPES)
    — same discovery engines as the main document search, just a different
    filetype list, kept in its own downloads/ subfolder and report section.
    """
    log(f"discovering critical/sensitive files ({', '.join(cfg.critical_file_types)}) ...")
    discovered = [d for d in discover_all(cfg, log, filetypes=cfg.critical_file_types, cache=cache)
                  if not _public_by_design(d.url)]
    log(f"  found {len(discovered)} critical file candidate(s)")
    if not discovered:
        return []

    if len(discovered) > cfg.max_docs:
        log(f"  capping to max_docs={cfg.max_docs}")
        discovered = discovered[: cfg.max_docs]

    os.makedirs(cfg.output_dir, exist_ok=True)
    critical_dir = os.path.join(cfg.output_dir, "critical_files")
    downloaded = download_documents(
        discovered, dest_dir=critical_dir, concurrency=cfg.concurrency,
        timeout=cfg.request_timeout, max_bytes=cfg.max_download_bytes, user_agent=cfg.user_agent,
    )
    ok_count = sum(1 for d in downloaded if not d.error)
    log(f"  {ok_count}/{len(downloaded)} critical file(s) downloaded successfully")
    return downloaded


# The engines that find files by following links or listing a host's URLs.
# The search-engine dorks spend one quota-counted "filetype:" query per
# extension, and web search does not answer those for pictures anyway.
_IMAGE_ENGINES = {"crawl", "sitemap", "wayback", "commoncrawl"}


def _leaking_urls(probe: ScanFindings) -> set[str]:
    """Pictures worth a line in the report: those with a location, a person
    or account, an address, an internal path or host, a classification label
    or a device serial number. The editing software and a bare camera model
    are on most photos and say little by themselves; they are reported only
    for a picture that made it here."""
    urls: set[str] = set()
    for bucket in (probe.geolocation, probe.usernames, probe.emails, probe.internal_paths,
                   probe.servers_and_printers, probe.classification_labels):
        for finding in bucket.values():
            urls.update(finding.document_urls)
    for finding in probe.devices.values():
        if "serial" in finding.field_name.lower():
            urls.update(finding.document_urls)
    return urls


def _read_images(cfg: ScanConfig, log: LogFn, cache: dict, *, skip_urls: set[str]) -> tuple[list, int]:
    """The opt-in image pass (ScanConfig.images): finds the pictures the
    site shows, reads their metadata and returns (the ones that leak
    something, how many were read). The rest are dropped rather than listed:
    a few hundred pictures with nothing in them would bury the documents."""
    engines = [e for e in cfg.engines if e in _IMAGE_ENGINES]
    log(f"discovering pictures ({', '.join(cfg.image_filetypes)}) ...")
    discovered = [d for d in discover_all(replace(cfg, engines=engines), log, filetypes=cfg.image_filetypes, cache=cache)
                  if d.url not in skip_urls]
    log(f"  found {len(discovered)} picture(s)")
    if not discovered:
        return [], 0
    if len(discovered) > cfg.max_images:
        log(f"  capping to max_images={cfg.max_images}")
        discovered = discovered[: cfg.max_images]

    downloaded = download_documents(
        discovered, dest_dir=os.path.join(cfg.output_dir, "images"), concurrency=cfg.concurrency,
        timeout=cfg.request_timeout, max_bytes=cfg.max_download_bytes, user_agent=cfg.user_agent,
    )
    read = [m for m in extract_metadata(downloaded) if not m.error]
    leaking = _leaking_urls(analyze(read, targets=cfg.targets))
    kept = [m for m in read if m.url in leaking]
    log(f"  {len(kept)} of {len(read)} picture(s) read carry something worth reporting")
    return kept, len(read)


def _scan_content(doc_metadata, content_categories: list[str], log: LogFn) -> list:
    categories = set(content_categories) or set()
    if not categories:
        return []

    missing = missing_dependencies(categories)
    if missing:
        log(
            "! content scan: missing optional dependencies (" + ", ".join(missing) + "). "
            "Install with `pip install 'metascout[content-scan]'` for full coverage; "
            "continuing with what's available."
        )

    log("scanning document content for personal/critical data (opt-in, heuristic) ...")
    hits = []
    for doc in doc_metadata:
        if doc.error:
            continue
        try:
            doc_hits = scan_document(doc.local_path, doc.filetype, categories=categories)
        except Exception as exc:
            log(f"! content scan failed for {doc.url}: {exc}")
            continue
        for h in doc_hits:
            h.document_url = doc.url
        hits.extend(doc_hits)

    if hits:
        log(f"  {len(hits)} potential sensitive-content hit(s) found — verify manually, this is heuristic, not confirmed")
    return hits


def scan_visual_signatures(doc_metadata, log: LogFn = _noop_log) -> list[ContentFinding]:
    """Runs the slow, experimental, image-based signature check
    (--visual-signature) over already-downloaded/extracted documents.

    Deliberately its own function, independent of _scan_content(), reused by
    both `run_scan()` (for a combined single-pass `metascout scan
    --visual-signature`) and the standalone `metascout visual-signature-scan`
    command (for running it later, on its own, against documents from a
    prior scan — this check alone can take on the order of a minute per
    document, so most users won't want it slowing down every scan).
    """
    missing = missing_visual_signature_dependencies()
    if missing:
        log(
            "! visual signature scan: missing optional dependencies (" + ", ".join(missing) + "). "
            "Install with `pip install 'metascout[visual-signature]'` (plus ImageMagick and "
            "Ghostscript, installed system-wide) to actually run this check."
        )
        return []

    log("scanning document page images for handwritten (wet) signatures (opt-in, slow, experimental) ...")
    hits = []
    for doc in doc_metadata:
        if doc.error:
            continue
        try:
            visually_signed = detect_visual_signature(doc.local_path, doc.filetype)
        except Exception as exc:
            log(f"! visual signature check failed for {doc.url}: {exc}")
            continue
        if visually_signed:
            hits.append(ContentFinding(
                document_url=doc.url, category="signature",
                masked_value="visual: signature-shaped ink detected in page image "
                             "(heuristic image analysis — verify manually)",
            ))

    if hits:
        log(f"  {len(hits)} potential visual signature hit(s) found — verify manually, this is experimental and heuristic")
    return hits


def run_local_document_scan(
    directory: str,
    *,
    filetypes: list[str],
    scan_content: bool = False,
    content_categories: list[str] | None = None,
    visual_signature: bool = False,
    critical_files: bool = False,
    critical_file_types: list[str] | None = None,
    log: LogFn = _noop_log,
) -> ScanFindings:
    """Analyzes documents already sitting on disk — metadata extraction,
    plus the same optional content-scan/visual-signature checks as
    `run_scan()` — with no discovery and no download step at all.

    For the case where someone already has a folder of documents (their own
    files, or ones gathered by some other means) and just wants them run
    through MetaScout's analysis, without pointing it at a live target.
    Shared by `metascout local-scan` and the web UI's standalone
    "scan existing documents" page — the same lean, discovery-free flow
    both use so they can't drift apart.
    """
    if not exiftool_available():
        raise RuntimeError(
            "exiftool not found on PATH. Install it first, e.g. "
            "`brew install exiftool` (macOS) or `apt install libimage-exiftool-perl` (Debian/Ubuntu)."
        )

    filetype_set = {ft.lower().lstrip(".") for ft in filetypes if ft.strip()}
    # Only actually used (non-empty) when critical_files is on — kept as its
    # own set so a file matching both lists (unusual, but possible with a
    # custom --filetypes) is still only ever counted once, under filetypes.
    critical_set = (
        {ft.lower().lstrip(".") for ft in (critical_file_types or []) if ft.strip()} - filetype_set
        if critical_files else set()
    )

    paths: list[str] = []
    critical_paths: list[str] = []
    for root, _, names in os.walk(directory):
        for name in names:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            full = os.path.join(root, name)
            if ext in filetype_set:
                paths.append(full)
            elif ext in critical_set:
                critical_paths.append(full)
    paths.sort()
    critical_paths.sort()

    log(f"found {len(paths)} matching document(s) in {directory}")
    if critical_files:
        log(f"found {len(critical_paths)} critical/sensitive file(s) in {directory}")

    def _as_downloaded(file_paths: list[str]) -> list[DownloadedDocument]:
        result = []
        for p in file_paths:
            ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
            try:
                size = os.path.getsize(p)
            except OSError:
                size = 0
            result.append(DownloadedDocument(
                url=f"file://{p}", local_path=p, filetype=ext,
                source=DiscoverySource.MANUAL, size_bytes=size,
            ))
        return result

    doc_metadata: list = []
    if not paths:
        log("No matching documents found. Nothing to analyze.")
        findings = analyze([], targets=[directory])
    else:
        downloaded = _as_downloaded(paths)
        log("extracting metadata with exiftool ...")
        doc_metadata = extract_metadata(downloaded)
        log("analyzing metadata ...")
        findings = analyze(doc_metadata, targets=[directory])

    critical_downloaded = _as_downloaded(critical_paths) if critical_paths else []
    findings.critical_files = [
        CriticalFile(url=d.url, filetype=d.filetype, source=d.source, size_bytes=d.size_bytes, error=d.error)
        for d in critical_downloaded
    ]

    content_hits: list[ContentFinding] = []
    if scan_content:
        content_hits.extend(_scan_content(doc_metadata, content_categories or [], log))
        if critical_downloaded:
            content_hits.extend(_scan_content(critical_downloaded, content_categories or [], log))
    if visual_signature:
        content_hits.extend(scan_visual_signatures(doc_metadata, log))
    findings.content_findings = content_hits

    return findings
