from __future__ import annotations

import urllib.robotparser
from collections import deque
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..models import DiscoveredDocument, DiscoverySource
from ._common import normalize_start_url

_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


def _load_robots(start_url: str, session: requests.Session, timeout: int) -> urllib.robotparser.RobotFileParser:
    parsed = urlparse(start_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    try:
        resp = session.get(robots_url, timeout=timeout)
        if resp.status_code == 200:
            parser.parse(resp.text.splitlines())
        else:
            parser.parse([])
    except requests.RequestException:
        parser.parse([])
    return parser


def crawl_site(
    target: str,
    filetypes: list[str],
    *,
    max_pages: int = 200,
    max_depth: int = 3,
    timeout: int = 15,
    user_agent: str = "MetaScout/0.1",
    respect_robots: bool = True,
) -> list[DiscoveredDocument]:
    """Breadth-first crawl of a single site, collecting links to documents of interest.

    Stays within the starting domain and only follows HTML pages; any link whose
    extension matches ``filetypes`` is recorded without being fetched.
    """
    start_url = normalize_start_url(target)
    start_netloc = urlparse(start_url).netloc

    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    robots = _load_robots(start_url, session, timeout) if respect_robots else None

    filetype_set = {ft.lower().lstrip(".") for ft in filetypes}
    found: dict[str, DiscoveredDocument] = {}
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if robots is not None and not robots.can_fetch(user_agent, url):
            continue

        try:
            resp = session.get(url, timeout=timeout, allow_redirects=True)
        except requests.RequestException:
            continue

        content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if resp.status_code != 200 or content_type not in _HTML_CONTENT_TYPES:
            continue

        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.find_all("a", href=True):
            link = urljoin(url, tag["href"]).split("#")[0]
            parsed = urlparse(link)
            if parsed.netloc != start_netloc or parsed.scheme not in ("http", "https"):
                continue

            ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path else ""
            if ext in filetype_set:
                if link not in found:
                    found[link] = DiscoveredDocument(url=link, source=DiscoverySource.CRAWL, filetype=ext)
                continue

            if depth < max_depth and link not in visited:
                queue.append((link, depth + 1))

    return list(found.values())
