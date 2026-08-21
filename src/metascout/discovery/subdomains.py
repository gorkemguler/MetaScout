from __future__ import annotations

import re

import requests

_CRTSH_ENDPOINT = "https://crt.sh/"
_HOSTNAME_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))*$")


def _is_valid_hostname(name: str) -> bool:
    return bool(name) and len(name) <= 253 and bool(_HOSTNAME_RE.match(name))


def _base_domain(target: str) -> str:
    domain = target.split("://", 1)[-1]
    domain = domain.split("/", 1)[0]
    return domain.split(":", 1)[0].lower()


def find_subdomains(
    target: str,
    *,
    timeout: int = 20,
    user_agent: str = "MetaScout/0.1",
    max_results: int = 500,
) -> list[str]:
    """Passive subdomain enumeration via crt.sh (Certificate Transparency log search).

    Free, keyless, and widely used for authorized recon. Returns a sorted list of
    unique hostnames (the apex domain itself is excluded). crt.sh can be slow or
    rate-limit under load, so failures degrade to an empty list rather than raising.
    """
    domain = _base_domain(target)
    session = requests.Session()
    session.headers["User-Agent"] = user_agent

    try:
        resp = session.get(
            _CRTSH_ENDPOINT,
            params={"q": f"%.{domain}", "output": "json"},
            timeout=timeout,
        )
        if resp.status_code != 200:
            return []
        data = resp.json()
    except (requests.RequestException, ValueError):
        return []

    subdomains: set[str] = set()
    for entry in data:
        name_value = entry.get("name_value", "")
        for raw_name in name_value.split("\n"):
            name = raw_name.strip().lower().lstrip("*.")
            if name and name != domain and name.endswith(f".{domain}") and _is_valid_hostname(name):
                subdomains.add(name)
            if len(subdomains) >= max_results:
                break
        if len(subdomains) >= max_results:
            break

    return sorted(subdomains)
