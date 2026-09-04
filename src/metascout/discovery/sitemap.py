from __future__ import annotations

from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from ..models import DiscoveredDocument, DiscoverySource
from ._common import normalize_start_url

_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def _fetch_xml(url: str, session: requests.Session, timeout: int) -> ElementTree.Element | None:
    try:
        resp = session.get(url, timeout=timeout)
        if resp.status_code != 200 or not resp.content:
            return None
        return ElementTree.fromstring(resp.content)
    except (requests.RequestException, ElementTree.ParseError):
        return None


def sitemap_search(
    target: str,
    filetypes: list[str],
    *,
    timeout: int = 15,
    user_agent: str = "MetaScout/0.1",
    max_sitemaps: int = 20,
) -> list[DiscoveredDocument]:
    """Discover document links referenced in sitemap.xml (and nested sitemap indexes)."""
    start_url = normalize_start_url(target)
    parsed = urlparse(start_url)
    filetype_set = {ft.lower().lstrip(".") for ft in filetypes}

    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    candidate_sitemaps = [f"{parsed.scheme}://{parsed.netloc}/sitemap.xml"]
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        resp = session.get(robots_url, timeout=timeout)
        if resp.status_code == 200:
            for line in resp.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    candidate_sitemaps.append(line.split(":", 1)[1].strip())
    except requests.RequestException:
        pass

    found: dict[str, DiscoveredDocument] = {}
    seen_sitemaps: set[str] = set()
    queue = list(dict.fromkeys(candidate_sitemaps))

    while queue and len(seen_sitemaps) < max_sitemaps:
        sitemap_url = queue.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        root = _fetch_xml(sitemap_url, session, timeout)
        if root is None:
            continue

        tag = root.tag.lower()
        if tag.endswith("sitemapindex"):
            for loc in root.findall(".//sm:sitemap/sm:loc", _NS) or root.findall(".//sitemap/loc"):
                if loc.text:
                    queue.append(loc.text.strip())
        elif tag.endswith("urlset"):
            for loc in root.findall(".//sm:url/sm:loc", _NS) or root.findall(".//url/loc"):
                if not loc.text:
                    continue
                link = loc.text.strip()
                link_path = urlparse(link).path
                ext = link_path.rsplit(".", 1)[-1].lower() if "." in link_path else ""
                if ext in filetype_set and link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.SITEMAP, filetype=ext)

    return list(found.values())
