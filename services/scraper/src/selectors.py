"""GrindVacPro — Shared platform selectors and slug resolution."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from shared.src.utils.url import _strip_www, _domain_matches

_SELECTORS_PATH = Path(__file__).resolve().parent.parent / "selectors.json"
_SEARCH_QUERIES_PATH = Path(__file__).resolve().parent.parent / "search_queries.json"

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


def load_search_queries() -> dict[str, dict]:
    """Load search query configurations from external JSON file.

    Returns a dict keyed by domain whose values contain ``base_url``,
    ``params`` (a list of dicts — each dict is a set of query parameters),
    ``use_pages_limiter`` (bool), and optional ``pages`` (int).
    """
    if not _SEARCH_QUERIES_PATH.exists():
        raise FileNotFoundError(f"Search queries file not found: {_SEARCH_QUERIES_PATH}")

    with _SEARCH_QUERIES_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"search_queries.json must be a JSON object, got {type(data).__name__}")

    for domain, cfg in data.items():
        if not isinstance(cfg, dict):
            raise ValueError(f"Domain '{domain}' must be a JSON object")
        if "base_url" not in cfg:
            raise ValueError(f"Domain '{domain}' missing required key 'base_url'")
        if "params" not in cfg:
            raise ValueError(f"Domain '{domain}' missing required key 'params'")
        if not isinstance(cfg["params"], list):
            raise ValueError(f"Domain '{domain}'.params must be a list of dicts")
        if not all(isinstance(p, dict) for p in cfg["params"]):
            raise ValueError(
                f"Domain '{domain}'.params must contain only dicts (query param sets)"
            )
        default_params = cfg.get("default_params")
        if default_params is not None:
            if not isinstance(default_params, dict):
                raise ValueError(
                    f"Domain '{domain}'.default_params must be a dict if present"
                )
        if cfg.get("use_pages_limiter", True) and "pages" not in cfg:
            raise ValueError(
                f"Domain '{domain}' has use_pages_limiter=True but missing 'pages' key"
            )

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