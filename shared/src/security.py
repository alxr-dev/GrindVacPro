"""GrindVacPro — SSRF protection and URL validation."""

from __future__ import annotations

import asyncio
import ipaddress
from urllib.parse import urlparse

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

    Prevents substring spoofing: ``hh.ru.evil.com`` does NOT match ``hh.ru``.
    """
    return hostname == domain or hostname.endswith("." + domain)


async def validate_url(url: str, allowed_domains: list[str]) -> None:
    """Validate that *url* is safe to fetch.

    Checks scheme, hostname against allowlist, and resolves the
    destination IP to block private/reserved ranges (SSRF protection).

    Args:
        url: The URL to validate.
        allowed_domains: List of permitted domain strings (e.g. ``["hh.ru"]``).

    Raises:
        ValueError: If the URL is not allowed.
    """
    parsed = urlparse(url)

    if parsed.scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"Disallowed URL scheme '{parsed.scheme}': {url}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Missing hostname in URL: {url}")

    hostname_lower = _strip_www(hostname.lower())

    # Must match a known platform domain (exact or suffix with dot boundary)
    if not any(_domain_matches(hostname_lower, domain) for domain in allowed_domains):
        raise ValueError(f"URL domain not in allowlist: {url}")

    if await _is_private_host(hostname):
        raise ValueError(f"URL resolves to private/reserved IP: {url}")
