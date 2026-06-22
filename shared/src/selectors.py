"""GrindVacPro — Shared platform selectors and slug resolution."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from shared.src.security import _strip_www, _domain_matches

_SELECTORS_PATH = Path("/app/selectors.json")

# Mapping: domain key in selectors.json → canonical platform slug
PLATFORM_SLUGS: dict[str, str] = {
    "hh.ru": "hh",
    "career.habr.com": "habr",
}


def load_selectors() -> dict:
    """Load and validate CSS selectors configuration from JSON file.

    Raises:
        FileNotFoundError: If the file is missing.
        ValueError: If the JSON structure is invalid.
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

    Raises:
        ValueError: When the domain is not configured.
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

    Raises:
        ValueError: When no match is found.
    """
    hostname = _strip_www(urlparse(url).netloc.lower())
    for domain in selectors:
        if _domain_matches(hostname, domain):
            return domain
    raise ValueError(f"Unsupported domain for URL: {url}")
