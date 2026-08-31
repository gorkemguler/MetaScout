from __future__ import annotations

import os
from typing import Callable
from urllib.parse import urlparse

from .config import ScanConfig
from .content_scan import detect_visual_signature, missing_dependencies, scan_document
from .discovery import brave_dork_search, crawl_site, ddgs_dork_search, find_subdomains, google_dork_search, serper_dork_search, sitemap_search, wayback_search
from .downloader import download_documents
from .metadata import exiftool_available, extract_metadata
from .metadata.analyzer import analyze
from .models import ContentFinding, DiscoveredDocument, DiscoverySource, DownloadedDocument, ScanFindings

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
            "Sorun yaşarsanız 'serper' motorunu (SERPER_API_KEY, https://serper.dev) ya da "
            "hiç anahtar gerektirmeyen '--engines ddgs --ddgs-backend google'ı deneyin."
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

    content_hits: list[ContentFinding] = []
    # Independent switches on purpose: the fast text/PII scan (--scan-content)
    # and the slow, experimental visual signature check (--visual-signature)
    # don't need each other — run whichever one(s) were actually asked for.
    if cfg.scan_content:
        content_hits.extend(_scan_content(doc_metadata, cfg.content_categories, log))
    if cfg.visual_signature:
        content_hits.extend(scan_visual_signatures(doc_metadata, log))
    findings.content_findings = content_hits

    return findings


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
    missing = missing_dependencies(set(), visual_signature=True)
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
    paths: list[str] = []
    for root, _, names in os.walk(directory):
        for name in names:
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext in filetype_set:
                paths.append(os.path.join(root, name))
    paths.sort()

    log(f"found {len(paths)} matching file(s) in {directory}")
    if not paths:
        log("No matching documents found. Nothing to analyze.")
        return analyze([], targets=[directory])

    downloaded = []
    for p in paths:
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        downloaded.append(DownloadedDocument(
            url=f"file://{p}", local_path=p, filetype=ext,
            source=DiscoverySource.MANUAL, size_bytes=size,
        ))

    log("extracting metadata with exiftool ...")
    doc_metadata = extract_metadata(downloaded)

    log("analyzing metadata ...")
    findings = analyze(doc_metadata, targets=[directory])

    content_hits: list[ContentFinding] = []
    if scan_content:
        content_hits.extend(_scan_content(doc_metadata, content_categories or [], log))
    if visual_signature:
        content_hits.extend(scan_visual_signatures(doc_metadata, log))
    findings.content_findings = content_hits

    return findings
