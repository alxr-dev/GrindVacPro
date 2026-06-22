"""GrindVacPro — Vacancy URL collector (search results scraper)."""

import asyncio
import json
import random
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from shared.src.database import get_session_maker
from shared.src.models import VacancyLink
from shared.src.security import validate_url
from shared.src.selectors import (
    load_selectors,
    resolve_platform_slug,
)
from shared.src.utils.logger import get_logger

logger = get_logger("scraper.search")

_SEARCH_QUERIES_PATH = Path("/app/search_queries.json")


def _load_search_queries() -> dict:
    """Load search query configurations from external JSON file.

    Returns a dict keyed by domain with ``base_url``, ``params``, and ``pages``.
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
        for key in ("base_url", "params", "pages"):
            if key not in cfg:
                raise ValueError(f"Domain '{domain}' missing required key '{key}'")

    return data


def _build_search_url(base_url: str, params: str, page: int) -> str:
    """Build a search URL with query parameters and page number.

    Args:
        base_url: The base search URL (e.g. ``https://hh.ru/search/vacancy``).
        params: URL-encoded query parameters string.
        page: Zero-based page number.

    Returns:
        Complete search URL with all parameters.
    """
    return f"{base_url}?{params}&page={page}"


async def _fetch_search_page(
    session: AsyncSession,
    url: str,
    selectors: dict,
    domain: str,
    allowed_domains: list[str],
) -> list[str]:
    """Fetch a search results page and extract vacancy URLs."""
    await asyncio.sleep(random.uniform(1.0, 1.5))

    try:
        response = await session.get(url, impersonate="chrome", timeout=30)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return []

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(response.text, "lxml")
    searcher_cfg = selectors[domain]["searcher"]
    link_selector = searcher_cfg["vacancy_link"]

    urls: list[str] = []
    for tag in soup.select(link_selector):
        href = tag.get("href")
        if href:
            if href.startswith("/"):
                parsed = urlparse(url)
                href = f"{parsed.scheme}://{parsed.netloc}{href}"
            try:
                await validate_url(href, allowed_domains)
            except ValueError as exc:
                logger.warning("Skipping unsafe URL: %s (%s)", href, exc)
                continue
            urls.append(href)

    return urls


async def _save_links(urls: list[str], selectors: dict) -> int:
    """Bulk-insert vacancy links, skipping duplicates (DB-level)."""
    if not urls:
        return 0

    maker = get_session_maker()
    rows: list[dict[str, str]] = []

    for url in urls:
        try:
            platform = resolve_platform_slug(url, selectors)
        except ValueError as exc:
            logger.warning("Skipping unsupported URL: %s (%s)", url, exc)
            continue
        rows.append({"url": url, "platform": platform, "status": "new"})

    if not rows:
        return 0

    async with maker() as session:
        stmt = (
            insert(VacancyLink)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(VacancyLink.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        return len(result.scalars().all())


async def run_search() -> None:
    """Collect vacancy URLs from search engine results and store them.

    Search queries are loaded from ``search_queries.json`` — an external
    configuration file that supports multiple platforms and parameter sets.
    Each platform can specify its own base URL, query parameters, and
    number of pages to scrape.
    """
    selectors = load_selectors()
    queries = _load_search_queries()

    # Build search URLs from external configuration
    search_urls: list[tuple[str, str]] = []
    for domain, cfg in queries.items():
        if domain not in selectors:
            logger.warning("Domain '%s' in search_queries.json not found in selectors.json, skipping", domain)
            continue
        if "searcher" not in selectors[domain]:
            logger.warning("Domain '%s' has no searcher config in selectors.json, skipping", domain)
            continue

        base_url = cfg["base_url"]
        params = cfg["params"]
        pages = cfg["pages"]

        for page in range(pages):
            url = _build_search_url(base_url, params, page)
            search_urls.append((domain, url))

    if not search_urls:
        logger.warning("No search URLs configured")
        return

    # Shuffle to distribute load across platforms
    random.shuffle(search_urls)

    allowed_domains = list(selectors.keys())

    async with AsyncSession() as http:
        for domain, url in search_urls:
            logger.info("Searching: %s", url)
            found = await _fetch_search_page(http, url, selectors, domain, allowed_domains)
            count = await _save_links(found, selectors)
            logger.info("Found %d links, saved %d new", len(found), count)
