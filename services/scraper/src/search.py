"""GrindVacPro — Vacancy URL collector (search results scraper)."""

import asyncio
import json
import random
from pathlib import Path
from urllib.parse import urlparse

from curl_cffi.requests import AsyncSession
from sqlalchemy import insert

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import VacancyLink
from shared.src.utils.logger import get_logger

logger = get_logger("scraper.search")

_SELECTORS_PATH = Path("/app/selectors.json")
_SEARCH_QUERY = "Python разработчик"
_SEARCH_PAGES = 3

# Platform slug mapping: domain → canonical slug
_PLATFORM_SLUGS: dict[str, str] = {
    "hh.ru": "hh",
    "career.habr.com": "habr",
}


def _load_selectors() -> dict:
    """Load CSS selectors configuration from JSON file."""
    if not _SELECTORS_PATH.exists():
        raise FileNotFoundError(f"Selectors file not found: {_SELECTORS_PATH}")
    with _SELECTORS_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_platform(url: str, selectors: dict) -> str:
    """Resolve URL to a platform slug via selectors.json domain keys.

    Raises ``ValueError`` when the domain is not configured.
    """
    hostname = urlparse(url).netloc.lower().lstrip("www.")
    for domain, slug in _PLATFORM_SLUGS.items():
        if domain in hostname:
            if domain not in selectors:
                raise ValueError(f"Domain '{domain}' not in selectors.json")
            return slug
    raise ValueError(f"Unsupported platform for URL: {url}")


async def _fetch_search_page(
    session: AsyncSession,
    url: str,
    selectors: dict,
    domain: str,
) -> list[str]:
    """Fetch a search results page and extract vacancy URLs."""
    await asyncio.sleep(random.uniform(1.0, 1.5))

    try:
        response = await session.get(url, impersonate="chrome")
        response.raise_for_status()
    except Exception as exc:
        logger.warning("Failed to fetch %s: %s", url, exc)
        return []

    from bs4 import BeautifulSoup  # local import to keep top clean

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
            urls.append(href)

    return urls


async def _save_links(urls: list[str], selectors: dict) -> int:
    """Batch-insert vacancy links, skipping duplicates (DB-level)."""
    if not urls:
        return 0

    maker = get_session_maker()
    inserted = 0

    async with maker() as session:
        for url in urls:
            try:
                platform = _resolve_platform(url, selectors)
            except ValueError as exc:
                logger.warning("Skipping unsupported URL: %s (%s)", url, exc)
                continue

            stmt = (
                insert(VacancyLink)
                .values(url=url, platform=platform, status="new")
                .on_conflict_do_nothing(index_elements=["url"])
            )
            result = await session.execute(stmt)
            if result.rowcount:
                inserted += 1

        await session.commit()

    return inserted


async def run_search() -> None:
    """Collect vacancy URLs from search engine results and store them."""
    selectors = _load_selectors()

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
