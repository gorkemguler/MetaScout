from __future__ import annotations

import re
from urllib.parse import urlparse

import requests

from ..models import DiscoveredDocument, DiscoverySource

_CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def wayback_search(
    target: str,
    filetypes: list[str],
    *,
    timeout: int = 20,
    user_agent: str = "MetaScout/0.1",
    max_results: int = 10000,
) -> list[DiscoveredDocument]:
    """Discover documents the Wayback Machine (archive.org) has ever archived
    for this host — including files that are no longer linked, or no longer
    reachable at all, on the live site. Free, no API key required.

    Queries the CDX Server API (https://web.archive.org/cdx/search/cdx) with
    a server-side regex filter on file extension to keep the response small.
    Scoped to exactly this host; subdomains are not included automatically
    (scan them separately via --subdomains, same as the other engines).

    Best-effort: any network/parse failure degrades to an empty list rather
    than raising, matching crawl/sitemap (no API key means no user-actionable
    quota-style error to surface).
    """
    host = target.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    filetype_set = {ft.lower().lstrip(".") for ft in filetypes if ft.strip()}
    if not host or not filetype_set:
        return []

    ext_pattern = "|".join(re.escape(ft) for ft in sorted(filetype_set))
    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    params = {
        "url": host,
        "matchType": "host",
        "output": "json",
        "fl": "original",
        "collapse": "urlkey",
        "filter": f"original:(?i).*\\.({ext_pattern})([?#].*)?$",
        "limit": str(max_results),
    }

    try:
        resp = session.get(_CDX_ENDPOINT, params=params, timeout=timeout)
    except requests.RequestException:
        return []
    if resp.status_code != 200 or not resp.text.strip():
        return []
    try:
        rows = resp.json()
    except ValueError:
        return []
    if not rows or len(rows) <= 1:
        return []

    found: dict[str, DiscoveredDocument] = {}
    for row in rows[1:]:
        if not row:
            continue
        url = row[0]
        ext = _ext_of(url)
        if ext not in filetype_set:
            continue
        if url not in found:
            found[url] = DiscoveredDocument(url=url, source=DiscoverySource.WAYBACK, filetype=ext)

    return list(found.values())
