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


# --- pictures a page shows, files on the site's other hosts, and the shared page cache ---

def test_crawl_site_collects_the_pictures_a_page_shows():
    home = _html_response(
        '<html><head><meta property="og:image" content="https://example.com/social/card.png"></head><body>'
        '<img src="/media/team.jpg">'
        '<img src="data:image/gif;base64,R0lGOD" data-src="/media/lazy.jpeg">'
        '<picture><source srcset="/media/hero.webp 1x, /media/hero@2x.webp 2x"><img src="/media/hero.jpg"></picture>'
        '<a href="/gallery/full.jpg">full size</a>'
        '<img src="/logo.svg">'
        '</body></html>'
    )
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["jpg", "jpeg", "png", "webp"])

    assert sorted(d.url for d in docs) == [
        "https://example.com/gallery/full.jpg", "https://example.com/media/hero.jpg",
        "https://example.com/media/hero.webp", "https://example.com/media/hero@2x.webp",
        "https://example.com/media/lazy.jpeg", "https://example.com/media/team.jpg",
        "https://example.com/social/card.png",
    ]


def test_crawl_site_asks_for_the_upload_behind_a_resized_copy():
    home = _html_response(
        '<img src="/wp-content/uploads/2026/01/office-300x200.jpg" '
        'srcset="/wp-content/uploads/2026/01/office-300x200.jpg 300w, /wp-content/uploads/2026/01/office-1024x683.jpg 1024w">'
        '<img src="/wp-content/uploads/2026/01/year-2026.jpg">'
    )
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("example.com", ["jpg"])

    # the three sizes of one picture are one original; "2026" is not a size
    assert sorted(d.url for d in docs) == ["https://example.com/wp-content/uploads/2026/01/office.jpg",
                                           "https://example.com/wp-content/uploads/2026/01/year-2026.jpg"]


def test_crawl_site_takes_files_from_the_sites_other_hosts_but_not_from_strangers():
    home = _html_response(
        '<a href="https://static.example.com/docs/annual.pdf">report</a>'
        '<a href="https://cdn.other-company.net/docs/theirs.pdf">not ours</a>'
        '<a href="https://notexample.com/docs/lookalike.pdf">lookalike</a>'
        '<img src="https://cdn.example.com/img/team.jpg">'
        '<img src="https://images.stock-photos.net/img/stock.jpg">'
    )
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://www.example.com": home}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = crawl_site("www.example.com", ["pdf", "jpg"])

    assert sorted(d.url for d in docs) == ["https://cdn.example.com/img/team.jpg",
                                           "https://static.example.com/docs/annual.pdf"]


def test_a_second_crawl_with_the_same_page_cache_fetches_nothing_again():
    home = _html_response('<a href="/about">about</a><a href="/report.pdf">r</a><img src="/team.jpg">')
    about = _html_response('<a href="/notes.env">n</a><img src="/office.jpg">')
    rules = {"robots.txt": _ALLOW_ALL_ROBOTS, "https://example.com/about": about, "https://example.com": home}
    cache = {}

    with patch("requests.Session.get", side_effect=_router(rules)) as get:
        documents = crawl_site("example.com", ["pdf"], page_cache=cache)
        pages_fetched = sum(1 for call in get.call_args_list if "robots.txt" not in call.args[0])
        pictures = crawl_site("example.com", ["jpg"], page_cache=cache)
        files = crawl_site("example.com", ["env"], page_cache=cache)
        pages_fetched_after = sum(1 for call in get.call_args_list if "robots.txt" not in call.args[0])

    assert [d.url for d in documents] == ["https://example.com/report.pdf"]
    assert sorted(d.url for d in pictures) == ["https://example.com/office.jpg", "https://example.com/team.jpg"]
    assert [d.url for d in files] == ["https://example.com/notes.env"]
    assert pages_fetched == 2  # the two pages; no linked file was fetched to look for links in it
    assert pages_fetched == pages_fetched_after  # the later crawls replayed the first one's pages
