from unittest.mock import MagicMock, patch

from metascout.discovery.subdomains import find_subdomains


def _fake_response(payload, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


def test_find_subdomains_dedupes_and_filters():
    payload = [
        {"name_value": "www.example.com\nmail.example.com"},
        {"name_value": "*.example.com"},
        {"name_value": "example.com"},
        {"name_value": "MAIL.example.com"},
        {"name_value": "not-a-subdomain-of.other.com"},
    ]
    with patch("requests.Session.get", return_value=_fake_response(payload)):
        result = find_subdomains("example.com")

    assert result == ["mail.example.com", "www.example.com"]


def test_find_subdomains_returns_empty_on_error():
    with patch("requests.Session.get", return_value=_fake_response({}, status_code=503)):
        result = find_subdomains("example.com")
    assert result == []


def test_find_subdomains_accepts_full_url_target():
    payload = [{"name_value": "api.example.com"}]
    with patch("requests.Session.get", return_value=_fake_response(payload)):
        result = find_subdomains("https://example.com/some/path")
    assert result == ["api.example.com"]
