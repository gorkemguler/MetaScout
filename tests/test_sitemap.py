from unittest.mock import MagicMock, patch

import requests

from metascout.discovery.sitemap import sitemap_search

_URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/report.pdf</loc></url>
  <url><loc>https://example.com/page.html</loc></url>
  <url><loc>https://example.com/notes.docx</loc></url>
</urlset>
"""

_EMPTY_ROBOTS = MagicMock(status_code=404, text="")


def _xml_response(body: str, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = body.encode("utf-8")
    return resp


def _router(rules: dict[str, MagicMock], default: MagicMock | None = None):
    """Returns a requests.Session.get side_effect that dispatches on URL."""
    def _get(url, *args, **kwargs):
        for substring, resp in rules.items():
            if substring in url:
                return resp
        if default is not None:
            return default
        raise AssertionError(f"unexpected request to {url}")
    return _get


def test_sitemap_search_parses_urlset_and_filters_by_extension():
    rules = {
        "robots.txt": _EMPTY_ROBOTS,
        "sitemap.xml": _xml_response(_URLSET),
    }
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = sitemap_search("example.com", ["pdf", "docx"])

    urls = {d.url for d in docs}
    assert urls == {"https://example.com/report.pdf", "https://example.com/notes.docx"}
    assert all(d.source == "sitemap" for d in docs)


def test_sitemap_search_follows_sitemapindex_nested_sitemaps():
    index = """<?xml version="1.0"?>
    <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/sitemap-docs.xml</loc></sitemap>
    </sitemapindex>
    """
    rules = {
        "robots.txt": _EMPTY_ROBOTS,
        "sitemap-docs.xml": _xml_response(_URLSET),
        "sitemap.xml": _xml_response(index),
    }
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = sitemap_search("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]


def test_sitemap_search_discovers_extra_sitemaps_from_robots_txt():
    robots = MagicMock(status_code=200, text="User-agent: *\nSitemap: https://example.com/custom-sitemap.xml\n")
    rules = {
        "robots.txt": robots,
        "custom-sitemap.xml": _xml_response(_URLSET),
        # the default /sitemap.xml candidate 404s — only the robots.txt-listed one has content
        "sitemap.xml": _xml_response("", status_code=404),
    }
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = sitemap_search("example.com", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]


def test_sitemap_search_degrades_gracefully_on_malformed_xml():
    rules = {"robots.txt": _EMPTY_ROBOTS, "sitemap.xml": _xml_response("not xml at all <<<")}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = sitemap_search("example.com", ["pdf"])
    assert docs == []


def test_sitemap_search_degrades_gracefully_on_network_error():
    with patch("requests.Session.get", side_effect=requests.RequestException("boom")):
        docs = sitemap_search("example.com", ["pdf"])
    assert docs == []


def test_sitemap_search_degrades_gracefully_on_http_error_status():
    rules = {"robots.txt": _EMPTY_ROBOTS, "sitemap.xml": _xml_response("", status_code=500)}
    with patch("requests.Session.get", side_effect=_router(rules)):
        docs = sitemap_search("example.com", ["pdf"])
    assert docs == []


def test_sitemap_search_dedupes_repeated_sitemap_urls_and_respects_max_sitemaps():
    # robots.txt lists the same default sitemap.xml URL twice — must not be
    # fetched (or counted against max_sitemaps) more than once.
    robots = MagicMock(status_code=200, text="Sitemap: https://example.com/sitemap.xml\nSitemap: https://example.com/sitemap.xml\n")
    fetch_count = {"n": 0}

    def _get(url, *args, **kwargs):
        if "robots.txt" in url:
            return robots
        fetch_count["n"] += 1
        return _xml_response(_URLSET)

    with patch("requests.Session.get", side_effect=_get):
        docs = sitemap_search("example.com", ["pdf"], max_sitemaps=5)

    assert fetch_count["n"] == 1
    assert [d.url for d in docs] == ["https://example.com/report.pdf"]


def test_sitemap_search_accepts_full_url_target():
    rules = {"robots.txt": _EMPTY_ROBOTS, "sitemap.xml": _xml_response(_URLSET)}
    with patch("requests.Session.get", side_effect=_router(rules)) as mock_get:
        docs = sitemap_search("https://example.com/some/path", ["pdf"])

    assert [d.url for d in docs] == ["https://example.com/report.pdf"]
    called_urls = [c.args[0] if c.args else c.kwargs.get("url") for c in mock_get.call_args_list]
    assert any(u.startswith("https://example.com/") for u in called_urls)
