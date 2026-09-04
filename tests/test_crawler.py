from unittest.mock import MagicMock, patch

import requests

from metascout.discovery.crawler import crawl_site

_ALLOW_ALL_ROBOTS = MagicMock(status_code=200, text="User-agent: *\nAllow: /\n")


def _html_response(body: str, status_code: int = 200, content_type: str = "text/html; charset=utf-8") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"Content-Type": content_type}
    resp.text = body
    return resp


def _router(rules: dict[str, MagicMock]):
    def _get(url, *args, **kwargs):
        if "robots.txt" in url:
            return rules.get("robots.txt", _ALLOW_ALL_ROBOTS)
        for substring, resp in rules.items():
            if substring != "robots.txt" and substring in url:
                return resp
        raise AssertionError(f"unexpected request to {url}")
    return _get


def test_crawl_site_finds_document_linked_from_start_page():
    home = _html_response('<html><body><a href="/report.pdf">Report</a></body></html>')
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]
    assert docs[0].source == "crawl"
    assert docs[0].filetype == "pdf"


def test_crawl_site_follows_links_within_domain_and_depth():
    home = _html_response('<html><body><a href="/page2">Page 2</a></body></html>')
    page2 = _html_response('<html><body><a href="/notes.docx">Notes</a></body></html>')
    rules = {
        "robots.txt": _ALLOW_ALL_ROBOTS,
        "https://example.com/page2": page2,
        "https://example.com": home,
    }
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["docx"], max_depth=3)

    assert [d.url for d in docs] == ["https://example.com/notes.docx"]


def test_crawl_site_does_not_follow_cross_domain_links():
    home = _html_response(
        '<html><body>'
        '<a href="https://other.com/external.pdf">External</a>'
        '<a href="/local.pdf">Local</a>'
        '</body></html>'
    )
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/local.pdf"]


def test_crawl_site_respects_max_depth_zero_only_crawls_start_page():
    home = _html_response('<html><body><a href="/page2">Page 2</a></body></html>')
    page2 = _html_response('<html><body><a href="/notes.docx">Notes</a></body></html>')
    rules = {
        "robots.txt": _ALLOW_ALL_ROBOTS,
        "https://example.com/page2": page2,
        "https://example.com": home,
    }
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["docx"], max_depth=0)

    # page2 itself isn't a matching filetype, and depth 0 means it's never
    # even queued for a fetch (its links, including notes.docx, are never seen).
    assert docs == []


def test_crawl_site_respects_robots_txt_disallow():
    disallow_robots = MagicMock(status_code=200, text="User-agent: *\nDisallow: /\n")
    home = _html_response('<html><body><a href="/report.pdf">Report</a></body></html>')
    rules = {"robots.txt": disallow_robots, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["pdf"], respect_robots=True)

    assert docs == []


def test_crawl_site_ignores_robots_txt_when_respect_robots_is_false():
    disallow_robots = MagicMock(status_code=200, text="User-agent: *\nDisallow: /\n")
    home = _html_response('<html><body><a href="/report.pdf">Report</a></body></html>')
    rules = {"robots.txt": disallow_robots, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["pdf"], respect_robots=False)

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]


def test_crawl_site_skips_non_html_content_type():
    home = _html_response("binary junk", content_type="application/octet-stream")
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["pdf"])

    assert docs == []


def test_crawl_site_degrades_gracefully_on_request_error():
    with patch("requests.Session.get", side_effect=requests.RequestException("boom")):
        docs = crawl_site("example.com", ["pdf"])
    assert docs == []


def test_crawl_site_dedupes_document_found_via_multiple_links():
    home = _html_response(
        '<html><body>'
        '<a href="/report.pdf">Copy 1</a>'
        '<a href="/report.pdf#section2">Copy 2 (same file, different fragment)</a>'
        '</body></html>'
    )
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]


def test_crawl_site_respects_max_pages():
    home = _html_response('<html><body><a href="/page2">Page 2</a><a href="/page3">Page 3</a></body></html>')
    page2 = _html_response('<html><body><a href="/a.pdf">a</a></body></html>')
    page3 = _html_response('<html><body><a href="/b.pdf">b</a></body></html>')
    rules = {
        "robots.txt": _ALLOW_ALL_ROBOTS,
        "https://example.com/page2": page2,
        "https://example.com/page3": page3,
        "https://example.com": home,
    }
    with patch("requests.Session.get", side_effect=_router(rules)):
        # max_pages=1 means only the start page itself gets fetched.
        docs = crawl_site("example.com", ["pdf"], max_pages=1)

    assert docs == []


def test_crawl_site_accepts_full_url_target_with_trailing_slash():
    home = _html_response('<html><body><a href="/report.pdf">Report</a></body></html>')
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("https://example.com/", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]
