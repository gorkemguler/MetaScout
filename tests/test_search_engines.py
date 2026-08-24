from unittest.mock import MagicMock, patch

import pytest

from metascout.discovery.search_engines import brave_dork_search, google_dork_search, serper_dork_search


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


def test_google_dork_search_rotates_to_next_key_on_quota_exhaustion():
    quota_error = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}
    page1 = {"items": [{"link": "https://example.com/a.pdf"}], "queries": {}}

    calls = []

    def fake_get(url, params, timeout):
        calls.append(params["key"])
        if params["key"] == "key-one":
            return _fake_response(quota_error, status_code=429)
        return _fake_response(page1)

    with patch("requests.Session.get", side_effect=fake_get):
        docs = google_dork_search("example.com", ["pdf"], api_key="key-one, key-two", cse_id="fake-cx")

    assert [d.url for d in docs] == ["https://example.com/a.pdf"]
    assert calls == ["key-one", "key-two"]


def test_google_dork_search_raises_after_all_keys_exhausted():
    quota_error = {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}

    with patch("requests.Session.get", return_value=_fake_response(quota_error, status_code=429)):
        with pytest.raises(RuntimeError, match="tried 2 key"):
            google_dork_search("example.com", ["pdf"], api_key="key-one,key-two", cse_id="fake-cx")


def test_serper_dork_search_requires_api_key():
    with pytest.raises(ValueError):
        serper_dork_search("example.com", ["pdf"], api_key="")


def test_serper_dork_search_collects_and_dedupes_results():
    page1 = {"organic": [{"link": "https://example.com/a.pdf"}, {"link": "https://example.com/b.pdf"}]}

    with patch("requests.Session.post", return_value=_fake_response(page1)):
        docs = serper_dork_search("example.com", ["pdf"], api_key="fake-key", max_results_per_type=30)

    urls = {d.url for d in docs}
    assert urls == {"https://example.com/a.pdf", "https://example.com/b.pdf"}
    assert all(d.source == "serper" for d in docs)


def test_serper_dork_search_never_requests_more_than_10_results_per_page():
    # Free-tier Serper accounts reject num > 10 with a 400 "Query pattern
    # not allowed for free accounts" error, so this must stay paginated.
    page1 = {"organic": [{"link": f"https://example.com/{i}.pdf"} for i in range(10)]}
    page2 = {"organic": [{"link": "https://example.com/extra.pdf"}]}

    seen_nums = []

    def fake_post(url, json, timeout):
        seen_nums.append(json["num"])
        return _fake_response(page1 if json["page"] == 1 else page2)

    with patch("requests.Session.post", side_effect=fake_post):
        docs = serper_dork_search("example.com", ["pdf"], api_key="fake-key", max_results_per_type=25)

    assert all(n <= 10 for n in seen_nums)
    assert len(docs) == 11


def test_serper_dork_search_raises_with_detail_on_first_request_failure():
    error_payload = {"message": "Not enough credits"}

    with patch("requests.Session.post", return_value=_fake_response(error_payload, status_code=403)):
        with pytest.raises(RuntimeError, match="credits"):
            serper_dork_search("example.com", ["pdf"], api_key="fake-key")
