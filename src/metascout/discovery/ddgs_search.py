from __future__ import annotations

from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from ..models import DiscoveredDocument, DiscoverySource


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _is_no_results_error(exc: Exception) -> bool:
    # DDGS raises a plain DDGSException (not a dedicated subclass) for the
    # completely normal case of a query having zero matches — most filetypes
    # won't exist on most sites, so this needs to be treated as "0 results",
    # not a failure, or a single not-found extension would wrongly abort the
    # whole engine for that host.
    return "no results" in str(exc).lower()


def ddgs_dork_search(
    target: str,
    filetypes: list[str],
    *,
    max_results_per_type: int = 30,
    timeout: int = 15,
    backend: str = "auto",
) -> list[DiscoveredDocument]:
    """Use DDGS (https://pypi.org/project/ddgs/) to run 'site:target filetype:X'
    dorks with no API key at all. Depending on `backend`, it scrapes
    DuckDuckGo directly or, with "auto" (the default), falls back across
    several engines (Bing, Brave, Google, Yandex, ...) until one responds.

    Since this is a scraper rather than an official API, it's the most
    fragile engine here in principle: result availability depends on
    whatever DDGS's maintainers currently keep working against each engine's
    anti-bot defenses, and sustained use can get rate-limited. In practice
    it's been reliable and fast in testing, so it's part of the default
    engine set — but treat it as a free bonus source, not a guaranteed one.

    A query genuinely matching nothing (most filetypes won't exist on most
    sites) surfaces from DDGS as an exception too, not an empty list — that
    case is treated as 0 results for that filetype rather than a failure.

    Raises RuntimeError if the very first query fails for a real reason
    (e.g. rate limited) so the caller can surface a clear reason instead of
    silently getting zero results. A failure after some results were
    already collected for other filetypes is treated as "no more
    available" and degrades gracefully, keeping what was found so far.
    """
    filetype_set = {ft.lower().lstrip(".") for ft in filetypes if ft.strip()}
    if not filetype_set:
        return []

    found: dict[str, DiscoveredDocument] = {}

    with DDGS(timeout=timeout) as ddgs:
        for ft in sorted(filetype_set):
            try:
                results = ddgs.text(
                    f"site:{target} filetype:{ft}",
                    backend=backend,
                    max_results=max_results_per_type,
                )
            except DDGSException as exc:
                if _is_no_results_error(exc):
                    continue
                if not found:
                    raise RuntimeError(f"DDGS search error (backend={backend}): {exc}") from exc
                continue
            except Exception as exc:  # unexpected error outside DDGS's own hierarchy
                if not found:
                    raise RuntimeError(f"DDGS search error (backend={backend}): {exc}") from exc
                continue

            for item in results or []:
                link = item.get("href")
                if not link:
                    continue
                ext = _ext_of(link)
                if ext not in filetype_set:
                    continue
                if link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.DDGS, filetype=ext)

    return list(found.values())
