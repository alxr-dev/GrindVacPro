"""GrindVacPro — Shared platform selectors and slug resolution."""

from __future__ import annotations

import ipaddress
import json
import socket
from pathlib import Path
from urllib.parse import urlparse

_SELECTORS_PATH = Path("/app/selectors.json")

# Mapping: domain key in selectors.json → canonical platform slug
PLATFORM_SLUGS: dict[str, str] = {
    "hh.ru": "hh",
    "career.habr.com": "habr",
}

# Schemes allowed for outbound HTTP requests
_ALLOWED_SCHEMES = {"https", "http"}

# Private/reserved IP ranges blocked to prevent SSRF
_PRIVATE_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


def _is_private_host(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private/reserved IP address."""
    try:
        addr = ipaddress.ip_address(hostname)
        return any(addr in net for net in _PRIVATE_NETWORKS)
    except ValueError:
        pass  # not a literal IP, try DNS

    try:
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            if any(addr in net for net in _PRIVATE_NETWORKS):
                return True
    except (socket.gaierror, OSError):
        return True  # unresolved → block

    return False


def validate_url(url: str, selectors: dict) -> None:
    """Validate that *url* is safe to fetch.

    Checks scheme, hostname, and resolves the destination IP to block
    private/reserved ranges (SSRF protection).

    Raises ``ValueError`` if the URL is not allowed.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme '{parsed.scheme}': {url}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Missing hostname in URL: {url}")

    # Must match a known platform domain
    hostname_lower = hostname.lower().lstrip("www.")
    if not any(domain in hostname_lower for domain in selectors):
        raise ValueError(f"URL domain not in selectors.json: {url}")

    if _is_private_host(hostname):
        raise ValueError(f"URL resolves to private/reserved IP: {url}")


def load_selectors() -> dict:
    """Load and validate CSS selectors configuration from JSON file.

    Raises ``FileNotFoundError`` if the file is missing.
    Raises ``ValueError`` if the JSON structure is invalid.
    """
    if not _SELECTORS_PATH.exists():
        raise FileNotFoundError(f"Selectors file not found: {_SELECTORS_PATH}")

    with _SELECTORS_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"selectors.json must be a JSON object, got {type(data).__name__}")

    for domain, cfg in data.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Domain '{domain}' must be a JSON object")
        for section in ("searcher", "parser"):
            if section not in cfg:
                raise ValueError(f"Domain '{domain}' missing required section '{section}'")
            if not isinstance(cfg[section], dict):
                raise ValueError(f"Domain '{domain}.{section}' must be a JSON object")
        if "vacancy_link" not in cfg.get("searcher", {}):
            raise ValueError(f"Domain '{domain}.searcher' missing 'vacancy_link' selector")

    return data


def resolve_platform_slug(url: str, selectors: dict) -> str:
    """Resolve a URL to its canonical platform slug.

    Matches the URL domain against ``selectors`` keys, then maps to slug
    via ``PLATFORM_SLUGS``.

    Raises ``ValueError`` when the domain is not configured.
    """
    hostname = urlparse(url).netloc.lower().lstrip("www.")
    for domain, slug in PLATFORM_SLUGS.items():
        if domain in hostname:
            if domain not in selectors:
                raise ValueError(f"Domain '{domain}' not in selectors.json")
            return slug
    raise ValueError(f"Unsupported platform for URL: {url}")


def resolve_domain(url: str, selectors: dict) -> str:
    """Match a URL domain to a key in *selectors*.

    Raises ``ValueError`` when no match is found.
    """
    hostname = urlparse(url).netloc.lower().lstrip("www.")
    for domain in selectors:
        if domain in hostname:
            return domain
    raise ValueError(f"Unsupported domain for URL: {url}")
