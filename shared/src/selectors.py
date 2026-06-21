"""GrindVacPro — Shared platform selectors and slug resolution."""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import json
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
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:0:0/96"),  # IPv4-mapped IPv6
]

# DNS resolution timeout in seconds
_DNS_TIMEOUT = 5


def _strip_www(hostname: str) -> str:
    """Remove 'www.' prefix from hostname (character-safe)."""
    if hostname.startswith("www."):
        return hostname[4:]
    return hostname


def _is_private_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address is in a private/reserved range.

    Handles IPv4-mapped IPv6 addresses by extracting the embedded IPv4.
    """
    # Handle IPv4-mapped IPv6: ::ffff:127.0.0.1 → 127.0.0.1
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr in net for net in _PRIVATE_NETWORKS)


async def _is_private_host(hostname: str) -> bool:
    """Return True if *hostname* resolves to a private/reserved IP address.

    Uses non-blocking DNS resolution with a timeout.
    """
    # Fast path: literal IP address
    try:
        addr = ipaddress.ip_address(hostname)
        return _is_private_ip(addr)
    except ValueError:
        pass  # not a literal IP, need DNS

    # Async DNS resolution with timeout
    try:
        loop = asyncio.get_running_loop()
        infos = await asyncio.wait_for(
            loop.getaddrinfo(hostname, None),
            timeout=_DNS_TIMEOUT,
        )
        for info in infos:
            addr = ipaddress.ip_address(info[4][0])
            if _is_private_ip(addr):
                return True
        return False
    except (asyncio.TimeoutError, OSError):
        # DNS resolution failed or timed out → block to be safe
        return True


def _domain_matches(hostname: str, domain: str) -> bool:
    """Check if *hostname* matches *domain* with proper boundary.

    Prevents substring spoofing: `hh.ru.evil.com` does NOT match `hh.ru`.
    """
    return hostname == domain or hostname.endswith("." + domain)


async def validate_url(url: str, selectors: dict) -> None:
    """Validate that *url* is safe to fetch.

    Checks scheme, hostname against allowlist, and resolves the
    destination IP to block private/reserved ranges (SSRF protection).

    Raises ``ValueError`` if the URL is not allowed.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme '{parsed.scheme}': {url}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Missing hostname in URL: {url}")

    hostname_lower = _strip_www(hostname.lower())

    # Must match a known platform domain (exact or suffix with dot boundary)
    if not any(_domain_matches(hostname_lower, domain) for domain in selectors):
        raise ValueError(f"URL domain not in selectors.json: {url}")

    if await _is_private_host(hostname):
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
    hostname = _strip_www(urlparse(url).netloc.lower())
    for domain, slug in PLATFORM_SLUGS.items():
        if _domain_matches(hostname, domain):
            if domain not in selectors:
                raise ValueError(f"Domain '{domain}' not in selectors.json")
            return slug
    raise ValueError(f"Unsupported platform for URL: {url}")


def resolve_domain(url: str, selectors: dict) -> str:
    """Match a URL domain to a key in *selectors*.

    Raises ``ValueError`` when no match is found.
    """
    hostname = _strip_www(urlparse(url).netloc.lower())
    for domain in selectors:
        if _domain_matches(hostname, domain):
            return domain
    raise ValueError(f"Unsupported domain for URL: {url}")
