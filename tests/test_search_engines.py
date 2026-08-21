from unittest.mock import MagicMock, patch

import pytest

from metascout.discovery.search_engines import brave_dork_search


def _fake_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_brave_dork_search_requires_api_key():
    with pytest.raises(ValueError):
        brave_dork_search("example.com", ["pdf"], api_key="")


def test_brave_dork_search_collects_and_dedupes_results():
    page1 = {"web": {"results": [{"url": "https://example.com/a.pdf"}, {"url": "https://example.com/b.pdf"}]}}
    page2 = {"web": {"results": []}}

    with patch("requests.Session.get", side_effect=[_fake_response(page1), _fake_response(page2)]):
        docs = brave_dork_search("example.com", ["pdf"], api_key="fake-token", max_results_per_type=30)

    urls = {d.url for d in docs}
    assert urls == {"https://example.com/a.pdf", "https://example.com/b.pdf"}
    assert all(d.source == "brave" for d in docs)
