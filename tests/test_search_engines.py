from unittest.mock import MagicMock, patch

import pytest

from metascout.discovery.search_engines import brave_dork_search, google_dork_search


def _fake_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    resp.text = str(payload)
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


def test_brave_dork_search_raises_with_detail_on_first_request_failure():
    error_payload = {"error": {"code": 429, "message": "Rate limit exceeded"}}

    with patch("requests.Session.get", return_value=_fake_response(error_payload, status_code=429)):
        with pytest.raises(RuntimeError, match="429"):
            brave_dork_search("example.com", ["pdf"], api_key="fake-token")


def test_brave_dork_search_sleeps_between_requests_but_not_before_the_first():
    page1 = {"web": {"results": [{"url": "https://example.com/a.pdf"}] * 20}}
    page2 = {"web": {"results": []}}

    with patch("requests.Session.get", side_effect=[_fake_response(page1), _fake_response(page2)]), \
         patch("metascout.discovery.search_engines.time.sleep") as mock_sleep:
        brave_dork_search("example.com", ["pdf"], api_key="fake-token", max_results_per_type=25)

    mock_sleep.assert_called_once()


def test_google_dork_search_raises_with_detail_when_quota_exceeded():
    error_payload = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded for quota metric 'Queries'"}}

    with patch("requests.Session.get", return_value=_fake_response(error_payload, status_code=429)):
        with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
            google_dork_search("example.com", ["pdf"], api_key="fake-key", cse_id="fake-cx")


def test_google_dork_search_degrades_gracefully_after_partial_results():
    page1 = {"items": [{"link": "https://example.com/a.pdf"}], "queries": {}}
    error_payload = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}

    with patch("requests.Session.get", side_effect=[_fake_response(page1), _fake_response(error_payload, status_code=429)]):
        docs = google_dork_search("example.com", ["pdf", "docx"], api_key="fake-key", cse_id="fake-cx")

    assert [d.url for d in docs] == ["https://example.com/a.pdf"]
