"""GrindVacPro — Shared URL utilities."""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def _strip_www(hostname: str) -> str:
    """Remove 'www.' prefix from hostname (character-safe)."""
    if hostname.startswith("www."):
        return hostname[4:]
    return hostname


def _domain_matches(hostname: str, domain: str) -> bool:
    """Check if *hostname* matches *domain* with proper boundary.

    Prevents substring spoofing: ``hh.ru.evil.com`` does NOT match ``hh.ru``.
    """
    return hostname == domain or hostname.endswith("." + domain)


def normalize_url(url: str) -> str:
    """Return a canonical URL for deduplication.

    Strips query parameters, fragment, and trailing slash so that
    different search-result URLs pointing to the same vacancy
    (e.g. differing only by ``?query=...&hhtmFrom=...``) collapse
    to a single canonical form.

    This function is **only** for identity comparison and DB storage.
    """
    parsed = urlparse(url)
    # Rebuild URL without query string or fragment
    clean = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    # Strip trailing slash for consistency
    return clean.rstrip("/") or clean
