from __future__ import annotations

import time
from urllib.parse import urlparse

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from ..models import DiscoveredDocument, DiscoverySource

# Consecutive empty/failed pages before we give up paginating a filetype.
# Google's scraped backend soft-blocks intermittently — a single empty page
# doesn't reliably mean "no more results" (confirmed live: page 3 errored,
# page 5 returned real results), so this needs to tolerate a few misses in a
# row rather than stopping on the first one.
_MAX_CONSECUTIVE_MISSES = 3


def _ext_of(url: str) -> str:
    path = urlparse(url).path
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _is_no_results_error(exc: Exception) -> bool:
    # DDGS raises a plain DDGSException (not a dedicated subclass) both for a
    # query with zero real matches AND, empirically, for a page that got
    # soft-blocked by the underlying engine — the message is identical
    # ("No results found.") either way, so it can't be used to tell the two
    # apart. Both cases are handled the same way here: treated as an empty
    # page rather than a fatal error.
    return "no results" in str(exc).lower()


def _fetch_page(
    ddgs: DDGS,
    query: str,
    *,
    backend: str,
    max_results: int,
    page: int,
    max_retries: int,
    retry_backoff: float,
) -> tuple[list[dict], Exception | None]:
    """Fetch one page of results, retrying transient failures with backoff.

    Returns (results, last_exception). `results` is `[]` on total failure;
    `last_exception` is set whenever the final attempt didn't return
    results, so the caller can tell "genuinely empty" apart from "gave up
    on you at this backend" — the value used for that "found or not"
    decision is fed by whether anything has been collected across all
    filetypes so far, not this return alone.
    """
    attempt = 0
    last_exc: Exception | None = None
    while attempt <= max_retries:
        try:
            return ddgs.text(query, backend=backend, max_results=max_results, page=page) or [], None
        except DDGSException as exc:
            last_exc = exc
            if _is_no_results_error(exc):
                return [], exc
        except Exception as exc:  # unexpected error outside DDGS's own hierarchy
            last_exc = exc
        attempt += 1
        if attempt <= max_retries:
            time.sleep(retry_backoff * attempt)
    return [], last_exc


def ddgs_dork_search(
    target: str,
    filetypes: list[str],
    *,
    max_results_per_type: int = 30,
    timeout: int = 15,
    backend: str = "auto",
    max_pages: int = 10,
    max_retries_per_page: int = 2,
    retry_backoff: float = 1.5,
) -> list[DiscoveredDocument]:
    """Use DDGS (https://pypi.org/project/ddgs/) to run 'site:target filetype:X'
    dorks with no API key at all. Depending on `backend`, it scrapes
    DuckDuckGo directly or, with "auto" (the default), falls back across
    several engines (Bing, Brave, Google, Yandex, ...) until one responds.

    A single DDGS call only returns one page of results (DDGS itself doesn't
    paginate a single backend), which is fine for `duckduckgo`/`auto` but
    badly undercounts `backend="google"` — live testing against a target
    with ~300 real Google results for one dork got only ~26 from a single
    call. This walks `page=1..max_pages` per filetype to collect more,
    stopping once `max_results_per_type` is reached, a page returns results
    that are all duplicates of what's already found, or
    `_MAX_CONSECUTIVE_MISSES` pages in a row come back empty/failed.

    Since this is a scraper rather than an official API, it's the most
    fragile engine here in principle: result availability depends on
    whatever DDGS's maintainers currently keep working against each
    engine's anti-bot defenses, and sustained use can get rate-limited or
    soft-blocked mid-pagination. Live testing against `backend="google"`
    confirmed this concretely: paginating 15 pages recovered only ~44 of
    ~300 real results, with more than half the page requests failing
    outright — so even with retries, `ddgs`+`google` should be treated as a
    free bonus source, not a substitute for `serper`/`google` when you need
    close to complete coverage.

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
            query = f"site:{target} filetype:{ft}"
            collected = 0
            consecutive_misses = 0
            page = 1
            last_exc: Exception | None = None

            while (
                collected < max_results_per_type
                and page <= max_pages
                and consecutive_misses < _MAX_CONSECUTIVE_MISSES
            ):
                results, exc = _fetch_page(
                    ddgs, query,
                    backend=backend, max_results=max_results_per_type - collected, page=page,
                    max_retries=max_retries_per_page, retry_backoff=retry_backoff,
                )
                if exc is not None:
                    last_exc = exc

                if not results:
                    consecutive_misses += 1
                    page += 1
                    continue

                new_count = 0
                for item in results:
                    link = item.get("href")
                    if not link:
                        continue
                    ext = _ext_of(link)
                    if ext not in filetype_set:
                        continue
                    if link not in found:
                        found[link] = DiscoveredDocument(url=link, source=DiscoverySource.DDGS, filetype=ext)
                        new_count += 1

                collected += len(results)
                page += 1
                if new_count == 0:
                    # Page had content but all of it was already seen — a
                    # sign the scraper is looping rather than paginating.
                    consecutive_misses += 1
                else:
                    consecutive_misses = 0

            if not found and last_exc is not None and not _is_no_results_error(last_exc):
                # Nothing at all has been found yet (across every filetype
                # tried so far), and this filetype's pagination gave up on a
                # real error (not "no results") — surface it instead of
                # returning a silent zero.
                raise RuntimeError(f"DDGS search error (backend={backend}): {last_exc}") from last_exc

    return list(found.values())
