from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from .models import DiscoveredDocument, DownloadedDocument


def _safe_filename(url: str, filetype: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    base = os.path.basename(urlparse(url).path) or "document"
    base = "".join(c for c in base if c.isalnum() or c in "._-")[:80]
    if not base.lower().endswith(f".{filetype}"):
        base = f"{base}.{filetype}"
    return f"{digest}_{base}"


def _fetch_to_file(
    fetch_url: str,
    local_path: str,
    session: requests.Session,
    timeout: int,
    max_bytes: int,
) -> tuple[str, int, str | None]:
    """Returns (sha256, size_bytes, error). Raises requests.RequestException/OSError on failure."""
    with session.get(fetch_url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            return "", 0, f"skipped: declared size {content_length} exceeds limit {max_bytes}"

        hasher = hashlib.sha256()
        size = 0
        with open(local_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    fh.close()
                    os.remove(local_path)
                    return "", 0, f"aborted: exceeded size limit {max_bytes}"
                hasher.update(chunk)
                fh.write(chunk)

    return hasher.hexdigest(), size, None


def _download_one(
    doc: DiscoveredDocument,
    dest_dir: str,
    session: requests.Session,
    timeout: int,
    max_bytes: int,
) -> DownloadedDocument:
    local_path = os.path.join(dest_dir, _safe_filename(doc.url, doc.filetype))
    # doc.url is used for the fetch first since it's the canonical URL other
    # engines would report for the same file (keeps cross-engine dedup and
    # the report consistent); archive_url (set only for Wayback Machine
    # results) is a fallback for when that original URL is no longer live —
    # exactly the case Wayback discovery exists to catch.
    urls_to_try = [doc.url] + ([doc.archive_url] if doc.archive_url and doc.archive_url != doc.url else [])
    last_error = "unknown error"

    for attempt_url in urls_to_try:
        try:
            sha256, size, skip_error = _fetch_to_file(attempt_url, local_path, session, timeout, max_bytes)
        except requests.RequestException as exc:
            last_error = str(exc)
            continue
        except OSError as exc:
            return DownloadedDocument(url=doc.url, local_path="", filetype=doc.filetype, source=doc.source, error=str(exc))

        if skip_error:
            return DownloadedDocument(url=doc.url, local_path="", filetype=doc.filetype, source=doc.source, error=skip_error)

        return DownloadedDocument(
            url=doc.url,
            local_path=local_path,
            filetype=doc.filetype,
            source=doc.source,
            sha256=sha256,
            size_bytes=size,
        )

    return DownloadedDocument(url=doc.url, local_path="", filetype=doc.filetype, source=doc.source, error=last_error)


def download_documents(
    documents: list[DiscoveredDocument],
    *,
    dest_dir: str,
    concurrency: int = 8,
    timeout: int = 15,
    max_bytes: int = 50 * 1024 * 1024,
    user_agent: str = "MetaScout/0.1",
) -> list[DownloadedDocument]:
    os.makedirs(dest_dir, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    results: list[DownloadedDocument] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_download_one, doc, dest_dir, session, timeout, max_bytes): doc
            for doc in documents
        }
        for future in as_completed(futures):
            results.append(future.result())

    return results
