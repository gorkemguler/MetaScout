from __future__ import annotations

from urllib.parse import urlparse

import requests

from ..models import DiscoveredDocument, DiscoverySource

_GOOGLE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
_BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


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

    The free tier caps at 100 queries/day and 10 results/query (max start=91),
    so this stays well within default quotas for a handful of filetypes.
    """
    if not api_key or not cse_id:
        raise ValueError("google_dork_search requires api_key and cse_id")

    session = requests.Session()
    found: dict[str, DiscoveredDocument] = {}

    for ft in filetypes:
        start = 1
        collected = 0
        while collected < max_results_per_type and start <= 91:
            params = {
                "key": api_key,
                "cx": cse_id,
                "q": f"site:{target} filetype:{ft}",
                "start": start,
                "num": min(10, max_results_per_type - collected),
            }
            resp = session.get(_GOOGLE_ENDPOINT, params=params, timeout=timeout)
            if resp.status_code != 200:
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
    """
    if not api_key:
        raise ValueError("brave_dork_search requires api_key")

    session = requests.Session()
    session.headers["Accept"] = "application/json"
    session.headers["X-Subscription-Token"] = api_key
    found: dict[str, DiscoveredDocument] = {}

    for ft in filetypes:
        page = 0
        collected = 0
        while collected < max_results_per_type:
            count = min(20, max_results_per_type - collected)
            params = {
                "q": f"site:{target} filetype:{ft}",
                "count": count,
                "offset": page,
            }
            resp = session.get(_BRAVE_ENDPOINT, params=params, timeout=timeout)
            if resp.status_code != 200:
                break
            data = resp.json()
            items = data.get("web", {}).get("results", [])
            if not items:
                break
            for item in items:
                link = item.get("url")
                if link and link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.BRAVE, filetype=_ext_of(link) or ft)
            collected += len(items)
            page += 1
            if len(items) < count:
                break

    return list(found.values())
