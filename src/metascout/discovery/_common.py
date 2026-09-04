from __future__ import annotations


def normalize_start_url(target: str) -> str:
    """Turns a bare domain or a full URL into a normalized https:// URL with
    no trailing slash, so callers can treat "example.com" and
    "https://example.com/" identically. Shared by crawler.py and sitemap.py
    (both discovery engines that need a single starting URL to work from).
    """
    if target.startswith("http://") or target.startswith("https://"):
        return target.rstrip("/")
    return f"https://{target.rstrip('/')}"
