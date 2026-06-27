"""GrindVacPro — Vacancy downloader and HTML parser pipeline."""

import asyncio
import random
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from curl_cffi.requests import AsyncSession
from sqlalchemy import select, update

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink
from shared.src.security import validate_url
from shared.src.utils.logger import get_logger
from .selectors import (
    load_selectors,
    resolve_domain,
    resolve_platform_slug,
)

logger = get_logger("scraper.pipeline")

_BATCH_SIZE = 20
_MAX_RETRIES = 3


async def _enqueue_transform(pool, vacancy_id: int) -> None:
    """Enqueue a *transform_vacancy* task into the arq ``html_queue``."""
    await pool.enqueue_job(
        "transform_vacancy",
        _queue_name="html_queue",
        vacancy_id=vacancy_id,
    )
    logger.info("Enqueued transform_vacancy for vacancy #%d", vacancy_id)


def _parse_vacancy(html: str, url: str, selectors: dict) -> dict | None:
    """Extract vacancy fields from HTML using platform-specific selectors."""
    from bs4 import BeautifulSoup

    try:
        domain = resolve_domain(url, selectors)
    except ValueError as exc:
        logger.warning("%s — skipping", exc)
        return None

    parser_cfg = selectors[domain]["parser"]
    soup = BeautifulSoup(html, "lxml")

    def _extract(field: str) -> str:
        selector = parser_cfg.get(field, "")
        if not selector:
            return ""
        # Support comma-separated fallback selectors
        for sel in selector.split(","):
            sel = sel.strip()
            tag = soup.select_one(sel)
            if tag:
                return tag.get_text(strip=True) if field != "description" else str(tag)
        return ""

    title = _extract("title")
    company_name = _extract("company_name")
    description_html = _extract("description")

    if not title or not description_html:
        logger.warning(
            "Incomplete parse for %s (title=%s, desc_len=%d)",
            url,
            bool(title),
            len(description_html),
        )
        return None

    platform = resolve_platform_slug(url, selectors)
    return {
        "platform": platform,
        "title": title,
        "company_name": company_name or "Unknown",
        "description_html": description_html,
    }


async def _fetch_html(session: AsyncSession, url: str, selectors: dict) -> str | None:
    """Download a page with rate limiting and retries. Returns HTML text or None."""
    try:
        await validate_url(url, list(selectors.keys()))
    except ValueError as exc:
        logger.warning("URL validation failed: %s", exc)
        return None

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        await asyncio.sleep(random.uniform(1.0, 1.5))
        try:
            response = await session.get(url, impersonate="chrome", timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt, _MAX_RETRIES, url, exc,
            )
            if attempt < _MAX_RETRIES:
                # Exponential backoff with jitter
                backoff = (2 ** attempt) + random.uniform(0.0, 1.0)
                await asyncio.sleep(backoff)

    logger.error("All %d attempts failed for %s: %s", _MAX_RETRIES, url, last_exc)
    return None


async def _mark_link_status(
    session, link_id: int, status: str, reason: str | None = None
) -> None:
    """Update the status of a vacancy link (no commit — caller manages transaction)."""
    values: dict[str, Any] = {"status": status}
    await session.execute(
        update(VacancyLink).where(VacancyLink.id == link_id).values(**values)
    )


async def _process_batch(
    http: AsyncSession,
    links: list[VacancyLink],
    selectors: dict,
    arq_pool,
) -> int:
    """Download, parse, and save a batch of vacancies. Returns count of saved."""
    maker = get_session_maker()
    saved = 0
    # Collect (vacancy_id, link_id, title) for enqueue after commit to avoid
    # a race condition where transformer picks up the task before the row is
    # visible in the database (uncommitted transaction).
    to_enqueue: list[tuple[int, int, str]] = []

    async with maker() as session:
        for link in links:
            html = await _fetch_html(http, link.url, selectors)
            if html is None:
                await _mark_link_status(session, link.id, "failed")
                continue

            parsed = _parse_vacancy(html, link.url, selectors)
            if parsed is None:
                await _mark_link_status(session, link.id, "failed")
                continue

            # Create vacancy record with temporary content_hash (updated by transformer)
            temp_hash = f"pending_{link.id}"
            vacancy = Vacancy(
                platform=parsed["platform"],
                title=parsed["title"],
                company_name=parsed["company_name"],
                description_html=parsed["description_html"],
                content_hash=temp_hash,
            )
            session.add(vacancy)
            await session.flush()

            # Link the vacancy_link to the new vacancy and mark as parsed
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.id == link.id)
                .values(vacancy_id=vacancy.id, status="parsed")
            )

            to_enqueue.append((vacancy.id, link.id, parsed["title"]))
            saved += 1
            logger.info("Saved vacancy #%d: %s", link.id, parsed["title"])

        await session.commit()

    # Enqueue to arq only after the transaction is committed, so transformer
    # can actually find the vacancy row when it picks up the task.
    for vacancy_id, link_id, title in to_enqueue:
        try:
            await _enqueue_transform(arq_pool, vacancy_id)
        except Exception as exc:
            logger.error("Failed to enqueue vacancy #%d: %s", vacancy_id, exc)
            # Mark link as failed since transformer will never process it
            async with maker() as session:
                await _mark_link_status(session, link_id, "failed")
                await session.commit()

    return saved


async def run_pipeline() -> None:
    """Fetch 'new' links, download HTML, parse, save vacancies, enqueue to arq."""
    selectors = load_selectors()
    maker = get_session_maker()

    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        async with AsyncSession() as http:
            while True:
                async with maker() as session:
                    result = await session.execute(
                        select(VacancyLink)
                        .where(VacancyLink.status == "new")
                        .limit(_BATCH_SIZE)
                    )
                    links = result.scalars().all()

                if not links:
                    logger.info("No more 'new' links to process")
                    break

                count = await _process_batch(http, links, selectors, arq_pool)
                logger.info("Batch processed: %d/%d saved", count, len(links))
    finally:
        await arq_pool.close()
