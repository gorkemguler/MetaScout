from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from .models import DiscoveredDocument, DownloadedDocument

# A site that answers a document URL with a cookie/bot-check page, a login
# form or a soft 404 still returns HTTP 200, so the status code alone can't
# tell us we got the document. These are the bytes a real file of each type
# starts with; anything else means we were served something other than the
# document — worth retrying via the archive, and never worth analyzing as if
# it were the real file.
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MAGIC_PREFIX = {
    "docx": (_ZIP_MAGIC,), "docm": (_ZIP_MAGIC,), "dotx": (_ZIP_MAGIC,),
    "xlsx": (_ZIP_MAGIC,), "xlsm": (_ZIP_MAGIC,), "pptx": (_ZIP_MAGIC,), "pptm": (_ZIP_MAGIC,),
    "odt": (_ZIP_MAGIC,), "ods": (_ZIP_MAGIC,), "odp": (_ZIP_MAGIC,), "odg": (_ZIP_MAGIC,),
    # Old binary Office formats are OLE2 compound files; Word also opens RTF
    # and Word-2.0 documents saved under a .doc name.
    "doc": (_OLE_MAGIC, b"{\\rt", b"\xdb\xa5"), "xls": (_OLE_MAGIC,), "ppt": (_OLE_MAGIC,),
}
# The PDF spec allows junk before %PDF (and real-world files use it), so this
# one is searched for near the start instead of anchored to byte 0.
_MAGIC_ANYWHERE = {"pdf": b"%PDF"}
_HEAD_BYTES = 1024


class NotTheDocument(Exception):
    """200 OK, but the bytes aren't the document that was asked for."""


def _describe_head(head: bytes) -> str:
    if not head.strip():
        return "an empty response"
    lowered = head.lstrip().lower()
    if lowered.startswith((b"<!doctype html", b"<html", b"<head", b"<script", b"<body")) or b"<html" in lowered[:200]:
        return "an HTML page (cookie/bot check, login form or soft 404?)"
    return "unexpected content"


def _check_looks_like(filetype: str, head: bytes) -> None:
    """Raises NotTheDocument when `head` can't be the start of `filetype`.
    Types with no known signature (.txt/.log/.env/... and manually supplied
    URLs without an extension) are left alone."""
    filetype = (filetype or "").lower()
    prefixes = _MAGIC_PREFIX.get(filetype)
    if prefixes and not head.startswith(prefixes):
        raise NotTheDocument(f"server returned {_describe_head(head)}, not a {filetype} file")
    anywhere = _MAGIC_ANYWHERE.get(filetype)
    if anywhere and anywhere not in head:
        raise NotTheDocument(f"server returned {_describe_head(head)}, not a {filetype} file")


def _safe_filename(url: str, filetype: str) -> str:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    base = os.path.basename(urlparse(url).path) or "document"
    base = "".join(c for c in base if c.isalnum() or c in "._-")[:80]
    # filetype can be empty for manually-supplied URLs without a recognizable
    # extension (e.g. a download endpoint like /files?id=123); leave the name
    # as-is rather than appending a bare trailing dot.
    if filetype and not base.lower().endswith(f".{filetype}"):
        base = f"{base}.{filetype}"
    return f"{digest}_{base}"


def _fetch_to_file(
    fetch_url: str,
    local_path: str,
    session: requests.Session,
    timeout: int,
    max_bytes: int,
    filetype: str = "",
) -> tuple[str, int, str | None]:
    """Returns (sha256, size_bytes, error). Raises requests.RequestException/
    OSError on failure, or NotTheDocument when the response isn't the file."""
    with session.get(fetch_url, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > max_bytes:
            return "", 0, f"skipped: declared size {content_length} exceeds limit {max_bytes}"

        hasher = hashlib.sha256()
        size = 0
        head = b""
        with open(local_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    fh.close()
                    os.remove(local_path)
                    return "", 0, f"aborted: exceeded size limit {max_bytes}"
                if len(head) < _HEAD_BYTES:
                    head += chunk[: _HEAD_BYTES - len(head)]
                hasher.update(chunk)
                fh.write(chunk)

    try:
        _check_looks_like(filetype, head)
    except NotTheDocument:
        # Keep nothing that isn't the document: it would otherwise be stored,
        # counted as a successful download and run through exiftool.
        os.remove(local_path)
        raise

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
            sha256, size, skip_error = _fetch_to_file(
                attempt_url, local_path, session, timeout, max_bytes, doc.filetype,
            )
        # NotTheDocument is retried like a failed fetch, which is exactly what
        # makes the Wayback fallback useful here: the live site hands out a
        # bot-check page, the archive still has the real document.
        except (requests.RequestException, NotTheDocument) as exc:
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
            archive_url=attempt_url if attempt_url != doc.url else None,
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
