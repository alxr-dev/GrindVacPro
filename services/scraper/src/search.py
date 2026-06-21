"""GrindVacPro — Vacancy URL collector (search results scraper)."""

import asyncio
import random
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession
from sqlalchemy import insert

from shared.src.database import get_session_maker
from shared.src.models import VacancyLink
from shared.src.selectors import (
    load_selectors,
    resolve_platform_slug,
    validate_url,
)
from shared.src.utils.logger import get_logger

logger = get_logger("scraper.search")

_SEARCH_QUERY = "Python разработчик"
_SEARCH_PAGES = 3


async def _fetch_search_page(
    session: AsyncSession,
    url: str,
    selectors: dict,
    domain: str,
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
                validate_url(href, selectors)
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
        # Use RETURNING + xmax trick: xmax=0 means actually inserted (not skipped by ON CONFLICT)
        stmt = (
            insert(VacancyLink)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["url"])
            .returning(VacancyLink.id)
        )
        result = await session.execute(stmt)
        await session.commit()
        return len(result.all())


async def run_search() -> None:
    """Collect vacancy URLs from search engine results and store them."""
    selectors = load_selectors()

    # Build search URLs for each configured platform
    search_urls: list[tuple[str, str]] = []
    for domain in selectors:
        if "searcher" not in selectors[domain]:
            continue
        for page in range(_SEARCH_PAGES):
            if "hh" in domain:
                search_urls.append((
                    domain,
                    f"https://hh.ru/search/vacancy?text={_SEARCH_QUERY}&page={page}",
                ))
            elif "habr" in domain:
                search_urls.append((
                    domain,
                    f"https://career.habr.com/vacancies?q={_SEARCH_QUERY}&page={page + 1}",
                ))

    if not search_urls:
        logger.warning("No search URLs configured in selectors.json")
        return

    async with AsyncSession() as http:
        for domain, url in search_urls:
            logger.info("Searching: %s", url)
            found = await _fetch_search_page(http, url, selectors, domain)
            count = await _save_links(found, selectors)
            logger.info("Found %d links, saved %d new", len(found), count)
