import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from metascout.discovery import commoncrawl
from metascout.discovery.commoncrawl import commoncrawl_search

CRAWLS = [{"id": f"CC-MAIN-2026-{n}", "cdx-api": f"https://index.commoncrawl.org/CC-MAIN-2026-{n}-index"}
          for n in (43, 39, 34)]


@pytest.fixture(autouse=True)
def _fresh_state():
    # What the module remembers between calls: the crawl list, and whether
    # the index is being given a rest after failing.
    commoncrawl._crawl_apis = None
    commoncrawl._failures_in_a_row = 0
    commoncrawl._paused_until = 0.0
    with patch("time.sleep"):
        yield


def _response(body, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = body if isinstance(body, str) else ""
    resp.json.return_value = body
    resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code}", response=resp) if status_code >= 400 else None
    return resp


def _rows(*rows):
    return "\n".join(json.dumps({"url": u, "timestamp": ts, "status": st}) for u, ts, st in rows)


def _index(per_query):
    """A fake index: collinfo.json first, then `per_query(api, host)` for each query."""
    calls = []

    def get(url, params=None, timeout=None):
        if url.endswith("collinfo.json"):
            return _response(CRAWLS)
        calls.append((url, params["url"]))
        return per_query(url, params["url"])
    return get, calls


def test_documents_come_from_the_two_newest_crawls_for_both_host_variants():
    get, calls = _index(lambda api, host: _response(_rows(
        (f"https://{host[:-2]}/{api[-8:-6]}.pdf", "20261014225109", "200"))))

    with patch("requests.Session.get", side_effect=get):
        docs = commoncrawl_search("example.com", ["pdf"])

    assert [c[1] for c in calls] == ["example.com/*", "www.example.com/*"] * 2
    assert {c[0] for c in calls} == {CRAWLS[0]["cdx-api"], CRAWLS[1]["cdx-api"]}  # not the third, older crawl
    assert {d.url for d in docs} == {"https://example.com/43.pdf", "https://www.example.com/43.pdf",
                                     "https://example.com/39.pdf", "https://www.example.com/39.pdf"}
    assert all(d.source == "commoncrawl" and d.filetype == "pdf" for d in docs)


def test_a_result_falls_back_to_the_wayback_capture_nearest_in_time():
    get, _ = _index(lambda api, host: _response(_rows(("https://example.com/gone.pdf", "20261014225109", "200"))))

    with patch("requests.Session.get", side_effect=get):
        [doc] = commoncrawl_search("example.com", ["pdf"])

    assert doc.archive_url == "https://web.archive.org/web/20261014225109id_/https://example.com/gone.pdf"


def test_only_successful_captures_of_the_wanted_types_count():
    get, _ = _index(lambda api, host: _response(_rows(
        ("https://example.com/a.PDF", "20261001000000", "200"),
        ("https://example.com/a.PDF", "20261002000000", "200"),      # same file, seen again
        ("https://example.com/moved.pdf", "20261001000000", "301"),
        ("https://example.com/page.html", "20261001000000", "200"),
        ("https://example.com/b.docx?v=2", "20261001000000", "200"),
    ) + "\nnot json\n"))

    with patch("requests.Session.get", side_effect=get):
        docs = commoncrawl_search("example.com", ["pdf", "docx"])

    assert sorted((d.url, d.filetype) for d in docs) == [("https://example.com/a.PDF", "pdf"),
                                                         ("https://example.com/b.docx?v=2", "docx")]


def test_the_query_asks_for_the_extensions_in_either_case():
    seen = {}

    def per_query(api, host):
        return _response("")

    get, _ = _index(per_query)

    def spy(url, params=None, timeout=None):
        if params:
            seen.update(params, timeout=timeout)
        return get(url, params=params, timeout=timeout)

    with patch("requests.Session.get", side_effect=spy):
        commoncrawl_search("https://example.com/", ["pdf", ".docx"], timeout=15, max_results=250)

    assert seen["filter"] == r"~url:.*\.(docx|DOCX|pdf|PDF)([?#].*)?$"
    assert seen["limit"] == "250"
    assert seen["timeout"] == 30  # the index needs longer than a scan's per-request timeout


def test_a_host_the_crawl_has_nothing_for_is_not_an_error():
    get, _ = _index(lambda api, host: _response("", status_code=404))

    with patch("requests.Session.get", side_effect=get):
        assert commoncrawl_search("example.com", ["pdf"]) == []
    assert commoncrawl._failures_in_a_row == 0


def test_a_bad_gateway_is_retried_once():
    answers = iter([_response("", status_code=502),
                    _response(_rows(("https://example.com/a.pdf", "20261001000000", "200")))])
    get, calls = _index(lambda api, host: next(answers, _response("")))

    with patch("requests.Session.get", side_effect=get):
        docs = commoncrawl_search("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/a.pdf"]
    assert calls[0] == calls[1]  # the same query again


def test_an_index_that_does_not_answer_says_so_and_is_left_alone_for_a_while():
    get, calls = _index(lambda api, host: _response("", status_code=504))

    with patch("requests.Session.get", side_effect=get):
        with pytest.raises(RuntimeError, match=r"did not answer \(HTTP 504\)"):
            commoncrawl_search("example.com", ["pdf"])
        asked = len(calls)
        with pytest.raises(RuntimeError, match="not asking again yet"):
            commoncrawl_search("sub.example.com", ["pdf"])

    assert asked == 6  # three queries, each tried twice, then it stops asking
    assert len(calls) == asked  # the next host cost no request at all


def test_one_failed_query_does_not_cost_the_others():
    def per_query(api, host):
        if host == "example.com/*":
            return _response("", status_code=504)
        return _response(_rows((f"https://www.example.com/{api[-8:-6]}.pdf", "20261001000000", "200")))

    get, _ = _index(per_query)

    with patch("requests.Session.get", side_effect=get):
        docs = commoncrawl_search("example.com", ["pdf"])

    assert {d.url for d in docs} == {"https://www.example.com/43.pdf", "https://www.example.com/39.pdf"}
    assert commoncrawl._paused_until == 0.0  # failures were never three in a row


def test_nothing_is_asked_without_a_host_or_filetypes():
    with patch("requests.Session.get") as get:
        assert commoncrawl_search("", ["pdf"]) == []
        assert commoncrawl_search("example.com", []) == []
    get.assert_not_called()
