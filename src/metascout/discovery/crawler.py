from __future__ import annotations

import re
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


# Attributes that name a picture a page shows: the plain ones, and the ones
# lazy-loading scripts (WordPress and most themes) park the real URL in.
_MEDIA_URL_ATTRS = ("src", "data-src", "data-lazy-src", "data-original")
_MEDIA_SET_ATTRS = ("srcset", "data-srcset", "data-lazy-srcset")
_SOCIAL_IMAGE_META = {"og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src"}
# "photo-300x200.jpg": a resized copy a CMS made of "photo.jpg". The copies
# are re-encoded and rarely keep any metadata; the upload they were made from
# usually does, and sits next to them under the name without the size.
_RESIZED_COPY_RE = re.compile(r"-\d{2,5}x\d{2,5}(?=\.[A-Za-z0-9]+$)")

# A link ending in one of these is a file, not a page. Following it to look
# for more links would download a whole PDF or video only to discard it, and
# a scan looking for one kind of file meets plenty of links to the others.
_NOT_A_PAGE = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp", "rtf", "csv", "txt", "log",
    "jpg", "jpeg", "png", "gif", "webp", "svg", "tif", "tiff", "heic", "bmp", "ico",
    "zip", "rar", "7z", "gz", "tar", "exe", "dmg", "apk", "iso",
    "mp3", "mp4", "avi", "mov", "wmv", "webm", "wav",
    "css", "js", "json", "xml", "woff", "woff2", "ttf", "eot",
    "sql", "bak", "env", "conf", "cfg", "ini", "yml", "yaml",
}

# One page's outgoing links: (links in <a href>, pictures the page shows).
# None for a page that could not be fetched or is not HTML.
PageLinks = tuple[list[str], list[str]]


def original_upload(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(path=_RESIZED_COPY_RE.sub("", parsed.path)).geturl()


def _page_links(url: str, html: str) -> PageLinks:
    soup = BeautifulSoup(html, "lxml")
    anchors = [urljoin(url, tag["href"]).split("#")[0] for tag in soup.find_all("a", href=True)]

    media: list[str] = []
    for tag in soup.find_all(["img", "source"]):
        media += [tag[attr] for attr in _MEDIA_URL_ATTRS if tag.get(attr)]
        for attr in _MEDIA_SET_ATTRS:
            # "a.jpg 1x, b.jpg 2x": each candidate is a URL and a size hint
            media += [part.split()[0] for part in (tag.get(attr) or "").split(",") if part.strip()]
    for tag in soup.find_all("meta", content=True):
        if (tag.get("property") or tag.get("name") or "").lower() in _SOCIAL_IMAGE_META:
            media.append(tag["content"])
    media = [urljoin(url, m.strip()).split("#")[0] for m in media if m.strip() and not m.strip().startswith("data:")]
    return anchors, media


def _same_site(host: str, start_host: str) -> bool:
    """The start host itself or a subdomain of it, taking "www." as part of
    neither: files linked from www.example.com are routinely served from
    static.example.com or cdn.example.com."""
    host, base = host.lower().split(":")[0], start_host.lower().split(":")[0]
    base = base[4:] if base.startswith("www.") else base
    return host == base or host.endswith(f".{base}")


def crawl_site(
    target: str,
    filetypes: list[str],
    *,
    max_pages: int = 200,
    max_depth: int = 3,
    timeout: int = 15,
    user_agent: str = "MetaScout/0.1",
    respect_robots: bool = True,
    page_cache: dict[str, PageLinks | None] | None = None,
) -> list[DiscoveredDocument]:
    """Breadth-first crawl of a single site, collecting links to files of interest.

    Only HTML pages on the starting host are followed. A link whose extension
    matches ``filetypes`` is recorded without being fetched, whether it is an
    ``<a href>`` or a picture the page shows, and whether it is on the
    starting host or a subdomain of the same site.

    A scan crawls the same site once per kind of file it looks for. Passing
    the same ``page_cache`` dict to each of those crawls makes the later ones
    reuse the pages the first one fetched instead of requesting them again.
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

    def record(link: str) -> bool:
        """Notes `link` if it is a wanted file on this site; True if it is a file at all."""
        parsed = urlparse(link)
        ext = parsed.path.rsplit(".", 1)[-1].lower() if "." in parsed.path.rsplit("/", 1)[-1] else ""
        if ext in filetype_set and parsed.scheme in ("http", "https") and _same_site(parsed.netloc, start_netloc):
            found.setdefault(link, DiscoveredDocument(url=link, source=DiscoverySource.CRAWL, filetype=ext))
        return ext in filetype_set or ext in _NOT_A_PAGE

    while queue and len(visited) < max_pages:
        url, depth = queue.popleft()
        if url in visited:
            continue
        visited.add(url)

        if robots is not None and not robots.can_fetch(user_agent, url):
            continue

        if page_cache is not None and url in page_cache:
            links = page_cache[url]
        else:
            links = None
            try:
                resp = session.get(url, timeout=timeout, allow_redirects=True)
            except requests.RequestException:
                resp = None
            if resp is not None:
                content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if resp.status_code == 200 and content_type in _HTML_CONTENT_TYPES:
                    links = _page_links(url, resp.text)
            if page_cache is not None:
                page_cache[url] = links
        if links is None:
            continue

        anchors, media = links
        for link in media:
            record(original_upload(link))
        for link in anchors:
            if record(link):
                continue
            parsed = urlparse(link)
            if parsed.netloc != start_netloc or parsed.scheme not in ("http", "https"):
                continue
            if depth < max_depth and link not in visited:
                queue.append((link, depth + 1))

    return list(found.values())
