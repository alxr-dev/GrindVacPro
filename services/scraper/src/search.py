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
from shared.src.utils.url import normalize_url
from shared.src.utils.logger import get_logger
from .selectors import (
    load_selectors,
    load_search_queries,
    resolve_platform_slug,
)

logger = get_logger("scraper.search")

# When use_pages_limiter is False, stop dynamic pagination after this many
# consecutive empty pages to avoid infinite loops.
_MAX_CONSECUTIVE_EMPTY_PAGES = 3


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
) -> tuple[list[str], bool]:
    """Fetch a search results page and extract vacancy URLs.

    Returns:
        A tuple of (urls, ok) where ``ok`` indicates the fetch itself
        succeeded (HTTP 200). ``urls`` may be empty on a successful fetch
        (no more results) or on a failure (network/HTTP error).
    """
    await asyncio.sleep(random.uniform(1.0, 1.5))

    try:
        response = await session.get(url, impersonate="chrome", timeout=30)
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return [], False

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

    return urls, True


async def _save_links(urls: list[str], selectors: dict) -> int:
    """Bulk-insert vacancy links, skipping duplicates (DB-level).

    URLs are normalized (query params stripped) before dedup and storage
    so that the same vacancy appearing in different search queries
    does not create duplicate rows. The caller still receives the full
    URLs for fetching.
    """
    if not urls:
        return 0

    maker = get_session_maker()
    rows: list[dict[str, str]] = []
    seen: set[str] = set()

    for url in urls:
        try:
            platform = resolve_platform_slug(url, selectors)
        except ValueError as exc:
            logger.warning("Skipping unsupported URL: %s (%s)", url, exc)
            continue

        canonical = normalize_url(url)
        if canonical in seen:
            continue
        seen.add(canonical)

        rows.append({"url": canonical, "platform": platform, "status": "new"})

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


async def _scrape_params_set(
    http: AsyncSession,
    base_url: str,
    params: str,
    domain: str,
    selectors: dict,
    allowed_domains: list[str],
    use_pages_limiter: bool,
    pages: int,
) -> None:
    """Scrape all pages for a single parameter set.

    When *use_pages_limiter* is True, scrape exactly *pages* pages.
    When False, use dynamic pagination: keep incrementing the page number
    until ``_MAX_CONSECUTIVE_EMPTY_PAGES`` consecutive pages return no links.
    """
    consecutive_empty = 0
    page = 0

    while True:
        url = _build_search_url(base_url, params, page)
        logger.info("Searching: %s", url)
        found, ok = await _fetch_search_page(http, url, selectors, domain, allowed_domains)

        if ok and found:
            count = await _save_links(found, selectors)
            logger.info("Found %d links, saved %d new", len(found), count)
        elif ok:
            logger.info("Page returned 0 links (end of results)")
        else:
            logger.warning("Page fetch failed, skipping")

        if use_pages_limiter:
            page += 1
            if page >= pages:
                break
        else:
            if ok and len(found) == 0:
                consecutive_empty += 1
                if consecutive_empty >= _MAX_CONSECUTIVE_EMPTY_PAGES:
                    logger.info(
                        "Dynamic pagination for %s: %d consecutive empty pages, stopping",
                        domain, consecutive_empty,
                    )
                    break
            elif ok:
                consecutive_empty = 0
            # On fetch failure, don't increment consecutive_empty —
            # transient errors shouldn't count toward the stop condition.
            page += 1


async def run_search() -> None:
    """Collect vacancy URLs from search engine results and store them.

    Search queries are loaded from ``search_queries.json`` — an external
    configuration file that supports multiple platforms and parameter sets.

    Each platform can specify:
    - ``base_url``: the search endpoint URL.
    - ``params``: a list of query-parameter strings. Each string is a complete
      set of search parameters (e.g. different search terms). The scraper
      iterates over every params entry for every platform.
    - ``use_pages_limiter``: if True, use the ``pages`` key to limit pagination.
      If False, use dynamic pagination — keep scraping until several consecutive
      pages return no results.
    - ``pages``: number of pages to scrape when ``use_pages_limiter`` is True.
    """
    selectors = load_selectors()
    queries = load_search_queries()

    # Build the full list of (domain, params_string) tuples to scrape
    scrape_tasks: list[tuple[str, str, bool, int]] = []
    for domain, cfg in queries.items():
        if domain not in selectors:
            logger.warning("Domain '%s' in search_queries.json not found in selectors.json, skipping", domain)
            continue
        if "searcher" not in selectors[domain]:
            logger.warning("Domain '%s' has no searcher config in selectors.json, skipping", domain)
            continue

        params_list = cfg["params"]
        use_pages_limiter = cfg.get("use_pages_limiter", True)
        pages = cfg.get("pages", 1)

        for params in params_list:
            scrape_tasks.append((domain, params, use_pages_limiter, pages))

    if not scrape_tasks:
        logger.warning("No search URLs configured")
        return

    # Shuffle to distribute load across platforms and param sets
    random.shuffle(scrape_tasks)

    allowed_domains = list(selectors.keys())

    async with AsyncSession() as http:
        for domain, params, use_pages_limiter, pages in scrape_tasks:
            await _scrape_params_set(
                http, base_url=queries[domain]["base_url"],
                params=params, domain=domain, selectors=selectors,
                allowed_domains=allowed_domains,
                use_pages_limiter=use_pages_limiter, pages=pages,
            )
