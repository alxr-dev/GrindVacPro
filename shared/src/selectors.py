"""GrindVacPro — Shared platform selectors and slug resolution."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

_SELECTORS_PATH = Path("/app/selectors.json")

# Mapping: domain key in selectors.json → canonical platform slug
PLATFORM_SLUGS: dict[str, str] = {
    "hh.ru": "hh",
    "career.habr.com": "habr",
}


def load_selectors() -> dict:
    """Load CSS selectors configuration from JSON file."""
    if not _SELECTORS_PATH.exists():
        raise FileNotFoundError(f"Selectors file not found: {_SELECTORS_PATH}")
    with _SELECTORS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


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
