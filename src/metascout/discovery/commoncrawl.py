from __future__ import annotations

import json
import re
import time
from urllib.parse import urlparse

import requests

from ..models import DiscoveredDocument, DiscoverySource
from .wayback import _host_variants

_COLLINFO_URL = "https://index.commoncrawl.org/collinfo.json"
# Each crawl is a different sample of the web, so a document missing from the
# newest one is often in the one before. Every extra crawl is another slow
# query per host variant, hence a small number.
_CRAWLS = 2
# The index answers in several seconds on a good day; the scan's own
# per-request timeout is tuned for the target site and is too short for it.
_MIN_TIMEOUT = 30
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_RETRY_SLEEP = 3.0
# After this many failed queries in a row the index is treated as down for a
# while: a scan with twenty subdomains would otherwise wait out a timeout for
# every one of them.
_FAILURES_BEFORE_PAUSE = 3
_PAUSE_SECONDS = 600

_crawl_apis: tuple[float, list[str]] | None = None
_failures_in_a_row = 0
_paused_until = 0.0


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _brief(exc: Exception) -> str:
    """"HTTP 504" or "ReadTimeout" — the exception's own text repeats the whole query URL."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def _newest_crawls(session: requests.Session, timeout: int) -> list[str]:
    """CDX endpoints of the newest crawls, newest first. The list changes
    every few weeks, so one lookup serves the whole process for a day."""
    global _crawl_apis
    if _crawl_apis and time.time() - _crawl_apis[0] < 86400:
        return _crawl_apis[1]
    resp = session.get(_COLLINFO_URL, timeout=timeout)
    resp.raise_for_status()
    apis = [c["cdx-api"] for c in resp.json() if c.get("cdx-api")][:_CRAWLS]
    _crawl_apis = (time.time(), apis)
    return apis


def _query(api: str, host: str, ext_pattern: str, session: requests.Session, timeout: int, limit: int) -> list[dict]:
    """One host in one crawl. Raises requests.RequestException when the index
    doesn't answer; a host the crawl simply has nothing for is an empty list."""
    params = {
        "url": f"{host}/*",
        "output": "json",
        "fl": "url,timestamp,status",
        # Case is spelled out in the alternation: the index's regex dialect
        # is not documented to take an inline (?i).
        "filter": f"~url:.*\\.({ext_pattern})([?#].*)?$",
        "limit": str(limit),
    }
    for attempt in (1, 2):
        resp = session.get(api, params=params, timeout=timeout)
        if resp.status_code == 404:  # how the index says "no captures for this URL"
            return []
        if resp.status_code in _RETRYABLE_STATUS and attempt == 1:
            time.sleep(_RETRY_SLEEP)
            continue
        resp.raise_for_status()
        break
    rows = []
    for line in resp.text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def commoncrawl_search(
    target: str,
    filetypes: list[str],
    *,
    timeout: int = 30,
    user_agent: str = "MetaScout/0.1",
    max_results: int = 1000,
) -> list[DiscoveredDocument]:
    """Discover documents Common Crawl has seen on this host, from the index
    of its newest crawls (https://index.commoncrawl.org). Free, no API key.

    Like the Wayback Machine it turns up files that are not linked from the
    site any more, but from an independent crawler, so the two overlap only
    partly. It is not one of the default engines: the index is slow (several
    seconds a query) and regularly answers 502/504.

    Scoped to the host and its www./apex counterpart, like wayback_search.
    Each result's `url` is the original URL, so it dedupes against the other
    engines. Common Crawl itself keeps only a truncated copy of large files,
    so `archive_url` points at the Wayback Machine's capture nearest in time
    instead; the downloader falls back to it when the live URL is gone, and
    gets a plain 404 there if the Wayback Machine never saw the file.

    Raises RuntimeError when the index is not answering, so the scan log says
    why this engine contributed nothing; after a couple of failures it stops
    asking for a while rather than waiting out a timeout per host.
    """
    global _failures_in_a_row, _paused_until

    host = target.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    filetype_set = {ft.lower().lstrip(".") for ft in filetypes if ft.strip()}
    if not host or not filetype_set:
        return []
    if time.time() < _paused_until:
        raise RuntimeError("the Common Crawl index was not answering a moment ago; not asking again yet")

    ext_pattern = "|".join(re.escape(e) for ft in sorted(filetype_set) for e in (ft, ft.upper()))
    timeout = max(timeout, _MIN_TIMEOUT)
    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    found: dict[str, DiscoveredDocument] = {}
    last_error = ""
    try:
        queries = [(api, variant) for api in _newest_crawls(session, timeout) for variant in _host_variants(host)]
    except (requests.RequestException, ValueError) as exc:
        queries, last_error = [], _brief(exc)
        _failures_in_a_row += 1

    for api, variant in queries:
        # One query failing says little about the next: the index times out
        # on one host and answers for another seconds later.
        try:
            rows = _query(api, variant, ext_pattern, session, timeout, max_results)
        except (requests.RequestException, ValueError) as exc:
            last_error = _brief(exc)
            _failures_in_a_row += 1
            if _failures_in_a_row >= _FAILURES_BEFORE_PAUSE:
                break
            continue
        _failures_in_a_row = 0
        for row in rows:
            url, timestamp = row.get("url", ""), row.get("timestamp", "")
            ext = _ext_of(url)
            if not url or url in found or ext not in filetype_set or str(row.get("status", "200")) != "200":
                continue
            found[url] = DiscoveredDocument(
                url=url, source=DiscoverySource.COMMONCRAWL, filetype=ext,
                archive_url=f"https://web.archive.org/web/{timestamp}id_/{url}" if timestamp else None,
            )

    if _failures_in_a_row >= _FAILURES_BEFORE_PAUSE:
        _paused_until = time.time() + _PAUSE_SECONDS
    if last_error and not found:
        raise RuntimeError(f"the Common Crawl index did not answer ({last_error})")
    return list(found.values())
