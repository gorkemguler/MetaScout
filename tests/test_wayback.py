from unittest.mock import MagicMock, patch

from metascout.discovery.wayback import wayback_search


def _fake_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "x" if payload else ""
    resp.json.return_value = payload
    return resp


def test_wayback_search_parses_cdx_json_rows():
    payload = [
        ["original"],
        ["https://example.com/old-report.pdf"],
        ["https://example.com/old-report.pdf?v=2"],
        ["https://example.com/notes.docx"],
    ]

    with patch("requests.Session.get", return_value=_fake_response(payload)):
        docs = wayback_search("example.com", ["pdf", "docx"])

    urls = {d.url for d in docs}
    assert urls == {
        "https://example.com/old-report.pdf",
        "https://example.com/old-report.pdf?v=2",
        "https://example.com/notes.docx",
    }
    assert all(d.source == "wayback" for d in docs)


def test_wayback_search_filters_out_non_matching_extensions_client_side():
    payload = [["original"], ["https://example.com/page.html"], ["https://example.com/file.pdf"]]

    with patch("requests.Session.get", return_value=_fake_response(payload)):
        docs = wayback_search("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/file.pdf"]


def test_wayback_search_returns_empty_on_no_rows():
    with patch("requests.Session.get", return_value=_fake_response([["original"]])):
        docs = wayback_search("example.com", ["pdf"])
    assert docs == []


def test_wayback_search_degrades_gracefully_on_http_error():
    with patch("requests.Session.get", return_value=_fake_response(None, status_code=503)):
        docs = wayback_search("example.com", ["pdf"])
    assert docs == []


def test_wayback_search_degrades_gracefully_on_network_error():
    import requests

    with patch("requests.Session.get", side_effect=requests.RequestException("boom")):
        docs = wayback_search("example.com", ["pdf"])
    assert docs == []


def test_wayback_search_accepts_full_url_target():
    payload = [["original"], ["https://example.com/file.pdf"]]

    with patch("requests.Session.get", return_value=_fake_response(payload)) as mock_get:
        docs = wayback_search("https://example.com/some/path", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/file.pdf"]
    called_params = mock_get.call_args.kwargs["params"]
    assert called_params["url"] == "example.com"
    assert called_params["matchType"] == "host"
