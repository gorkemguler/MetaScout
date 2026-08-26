from __future__ import annotations

import time
from urllib.parse import urlparse

import requests

from ..models import DiscoveredDocument, DiscoverySource

_GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"
_SERPER_ENDPOINT = "https://google.serper.dev/search"

# Brave's free tier is rate-limited to ~1 request/second; without a delay,
# looping over several filetypes back-to-back trips it and every request
# after the first silently 429s.
_BRAVE_REQUEST_DELAY = 1.1


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _http_error_detail(resp: requests.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return (resp.text or "").strip()[:200] or f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            parts = [str(err[k]) for k in ("status", "message", "code") if err.get(k)]
            if parts:
                return " ".join(parts)
        for key in ("message", "error", "detail"):
            if data.get(key):
                return str(data[key])
    return (resp.text or "").strip()[:200] or f"HTTP {resp.status_code}"


def google_dork_search(
    target: str,
    filetypes: list[str],
    *,
    api_key: str,
    cse_id: str,
    max_results_per_type: int = 30,
    timeout: int = 15,
) -> list[DiscoveredDocument]:
    """Use Google Programmable Search Engine (Custom Search JSON API) to run
    'site:target filetype:X' dorks. Requires a Google API key and CSE id.

    Google is discontinuing this API on 2027-01-01, and has already closed it
    to new customers — newly created Google Cloud projects get a permanent
    403 PERMISSION_DENIED regardless of configuration. If this keeps failing,
    try the `serper` engine instead (see serper_dork_search below), or the
    keyless `ddgs` engine with `backend="google"` (see discovery/ddgs_search.py)
    — confirmed working live: real Google results, no API key at all.

    The free tier caps at 100 queries/day and 10 results/query (max start=91),
    so this stays well within default quotas for a handful of filetypes.

    `api_key` may be a comma-separated list of keys (e.g. from separate GCP
    projects sharing the same `cse_id`). When one is rejected for quota/auth
    reasons (HTTP 403/429), the next key is used automatically and the scan
    continues without losing progress.

    Raises RuntimeError if every key fails on the very first request (e.g.
    all quotas exhausted, bad key) so the caller can surface a clear reason
    instead of silently getting zero results. A failure after some results
    were already collected is treated as "no more available" and returns
    what was found so far.
    """
    keys = [k.strip() for k in api_key.split(",")] if api_key else []
    keys = [k for k in keys if k]
    if not keys or not cse_id:
        raise ValueError("google_dork_search requires api_key and cse_id")

    session = requests.Session()
    found: dict[str, DiscoveredDocument] = {}
    key_idx = 0

    def _request(params: dict) -> requests.Response:
        nonlocal key_idx
        while True:
            resp = session.get(_GOOGLE_ENDPOINT, params={**params, "key": keys[key_idx]}, timeout=timeout)
            if resp.status_code == 200 or resp.status_code not in (403, 429) or key_idx == len(keys) - 1:
                return resp
            key_idx += 1

    for ft in filetypes:
        start = 1
        collected = 0
        while collected < max_results_per_type and start <= 91:
            params = {
                "cx": cse_id,
                "q": f"site:{target} filetype:{ft}",
                "start": start,
                "num": min(10, max_results_per_type - collected),
            }
            resp = _request(params)
            if resp.status_code != 200:
                if not found:
                    keys_note = f" (tried {len(keys)} key(s))" if len(keys) > 1 else ""
                    raise RuntimeError(f"Google Custom Search API error (HTTP {resp.status_code}){keys_note}: {_http_error_detail(resp)}")
                break
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break
            for item in items:
                link = item.get("link")
                if link and link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.GOOGLE, filetype=_ext_of(link) or ft)
            collected += len(items)
            start += len(items)
            if "nextPage" not in data.get("queries", {}):
                break

    return list(found.values())


def brave_dork_search(
    target: str,
    filetypes: list[str],
    *,
    api_key: str,
    max_results_per_type: int = 30,
    timeout: int = 15,
) -> list[DiscoveredDocument]:
    """Use the Brave Search API to run 'site:target filetype:X' dorks.
    Requires a Brave Search API subscription token: https://brave.com/search/api/

    Brave's `offset` parameter is page-based (in units of `count`), unlike
    Google's result-based offset, so it is incremented per request here.

    Raises RuntimeError if the very first request fails (e.g. rate limited,
    bad key) so the caller can surface a clear reason instead of silently
    getting zero results. A failure after some results were already collected
    is treated as "no more available" and returns what was found so far.
    """
    if not api_key:
        raise ValueError("brave_dork_search requires api_key")

    session = requests.Session()
    session.headers["Accept"] = "application/json"
    session.headers["X-Subscription-Token"] = api_key
    found: dict[str, DiscoveredDocument] = {}
    got_any_result = False
    request_count = 0

    for ft in filetypes:
        page = 0
        collected = 0
        while collected < max_results_per_type:
            if request_count > 0:
                time.sleep(_BRAVE_REQUEST_DELAY)
            request_count += 1

            count = min(20, max_results_per_type - collected)
            params = {
                "q": f"site:{target} filetype:{ft}",
                "count": count,
                "offset": page,
            }
            resp = session.get(_BRAVE_ENDPOINT, params=params, timeout=timeout)
            if resp.status_code != 200:
                if not got_any_result:
                    raise RuntimeError(f"Brave Search API error (HTTP {resp.status_code}): {_http_error_detail(resp)}")
                break
            data = resp.json()
            items = data.get("web", {}).get("results", [])
            if not items:
                break
            got_any_result = True
            for item in items:
                link = item.get("url")
                if link and link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.BRAVE, filetype=_ext_of(link) or ft)
            collected += len(items)
            page += 1
            if len(items) < count:
                break

    return list(found.values())


def serper_dork_search(
    target: str,
    filetypes: list[str],
    *,
    api_key: str,
    max_results_per_type: int = 30,
    timeout: int = 15,
) -> list[DiscoveredDocument]:
    """Use Serper.dev to run 'site:target filetype:X' dorks against real
    Google search results. Requires a Serper API key: https://serper.dev

    This is a third-party service that re-serves Google's public search
    results — not an official Google product. It exists as a practical
    stand-in now that Google's own Custom Search JSON API is being
    discontinued (2027-01-01) and already rejects new Google Cloud projects.

    Free-tier Serper accounts reject `num` above 10 per request with a 400
    "Query pattern not allowed for free accounts" error, so requests are
    capped at 10 and paginated via `page` instead — this also works fine on
    paid accounts, just in more (still free) round trips.

    Raises RuntimeError if the very first request fails (e.g. bad key, no
    credit left) so the caller can surface a clear reason instead of
    silently getting zero results. A failure after some results were
    already collected is treated as "no more available" and returns what
    was found so far.
    """
    if not api_key:
        raise ValueError("serper_dork_search requires api_key")

    session = requests.Session()
    session.headers["X-API-KEY"] = api_key
    session.headers["Content-Type"] = "application/json"
    found: dict[str, DiscoveredDocument] = {}

    for ft in filetypes:
        page = 1
        collected = 0
        while collected < max_results_per_type:
            num = min(10, max_results_per_type - collected)
            body = {"q": f"site:{target} filetype:{ft}", "num": num, "page": page}
            resp = session.post(_SERPER_ENDPOINT, json=body, timeout=timeout)
            if resp.status_code != 200:
                if not found:
                    raise RuntimeError(f"Serper API error (HTTP {resp.status_code}): {_http_error_detail(resp)}")
                break
            data = resp.json()
            items = data.get("organic", [])
            if not items:
                break
            for item in items:
                link = item.get("link")
                if link and link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.SERPER, filetype=_ext_of(link) or ft)
            collected += len(items)
            page += 1
            if len(items) < num:
                break

    return list(found.values())
