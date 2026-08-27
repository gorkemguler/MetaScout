from unittest.mock import MagicMock, patch

import pytest

from ddgs.exceptions import DDGSException

from metascout.discovery.ddgs_search import ddgs_dork_search


def _mock_ddgs(text_side_effect):
    instance = MagicMock()
    instance.text.side_effect = text_side_effect
    ctx = MagicMock()
    ctx.__enter__.return_value = instance
    ctx.__exit__.return_value = False
    return ctx


def test_ddgs_dork_search_collects_and_dedupes_results():
    payload = [
        {"title": "a", "href": "https://example.com/a.pdf", "body": "..."},
        {"title": "b", "href": "https://example.com/a.pdf", "body": "duplicate"},
        {"title": "c", "href": "https://example.com/b.pdf", "body": "..."},
    ]

    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(lambda *a, **k: payload)):
        docs = ddgs_dork_search("example.com", ["pdf"])

    urls = {d.url for d in docs}
    assert urls == {"https://example.com/a.pdf", "https://example.com/b.pdf"}
    assert all(d.source == "ddgs" for d in docs)


def test_ddgs_dork_search_filters_by_extension_client_side():
    payload = [
        {"href": "https://example.com/page.html"},
        {"href": "https://example.com/file.pdf"},
    ]

    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(lambda *a, **k: payload)):
        docs = ddgs_dork_search("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/file.pdf"]


def test_ddgs_dork_search_raises_with_detail_on_first_query_failure():
    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(RuntimeError("rate limited"))), \
            patch("metascout.discovery.ddgs_search.time.sleep"):
        with pytest.raises(RuntimeError, match="rate limited"):
            ddgs_dork_search("example.com", ["pdf"])


def test_ddgs_dork_search_degrades_gracefully_after_partial_results():
    # filetypes are processed in sorted order ("doc" before "pdf"); the first
    # (doc) succeeds, giving `found` some content before the second (pdf)
    # fails, so that failure should degrade gracefully instead of raising.
    doc_payload = [{"href": "https://example.com/a.doc"}]

    def side_effect(query, **kwargs):
        if "filetype:doc" in query:
            return doc_payload
        raise RuntimeError("blocked")

    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(side_effect)), \
            patch("metascout.discovery.ddgs_search.time.sleep"):
        docs = ddgs_dork_search("example.com", ["doc", "pdf"])

    assert [d.url for d in docs] == ["https://example.com/a.doc"]


def test_ddgs_dork_search_treats_no_results_as_empty_not_an_error():
    # DDGS raises a DDGSException("No results found.") for a query that
    # simply has zero matches — this must NOT be treated as a failure, even
    # when it's the only/first filetype tried.
    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(DDGSException("No results found."))):
        docs = ddgs_dork_search("example.com", ["pdf"])
    assert docs == []


def test_ddgs_dork_search_no_results_for_one_filetype_does_not_block_another():
    # Regression: a "no results" on the alphabetically-first filetype used
    # to abort the whole call before the second filetype (with real results)
    # was ever tried.
    pdf_payload = [{"href": "https://example.com/a.pdf"}]

    def side_effect(query, **kwargs):
        if "filetype:doc" in query:
            raise DDGSException("No results found.")
        return pdf_payload

    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(side_effect)):
        docs = ddgs_dork_search("example.com", ["doc", "pdf"])

    assert [d.url for d in docs] == ["https://example.com/a.pdf"]


def test_ddgs_dork_search_real_ratelimit_error_still_raises():
    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(DDGSException("Ratelimit"))), \
            patch("metascout.discovery.ddgs_search.time.sleep"):
        with pytest.raises(RuntimeError, match="Ratelimit"):
            ddgs_dork_search("example.com", ["pdf"])


def test_ddgs_dork_search_passes_query_and_backend_through():
    captured = {}

    def side_effect(query, backend=None, max_results=None, page=None):
        captured["query"] = query
        captured["backend"] = backend
        captured["max_results"] = max_results
        return []

    with patch("metascout.discovery.ddgs_search.DDGS", return_value=_mock_ddgs(side_effect)), \
            patch("metascout.discovery.ddgs_search.time.sleep"):
        ddgs_dork_search("example.com", ["pdf"], backend="duckduckgo", max_results_per_type=15)

    assert captured["query"] == "site:example.com filetype:pdf"
    assert captured["backend"] == "duckduckgo"
    assert captured["max_results"] == 15
