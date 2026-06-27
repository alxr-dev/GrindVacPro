"""GrindVacPro — Scraper service entry point."""

import asyncio

from shared.src.utils.logger import get_logger

from .pipeline import run_pipeline
from .search import run_search

logger = get_logger("scraper.main")


async def main() -> None:
    """Orchestrate search → pipeline → arq enqueue."""
    logger.info("Scraper service starting")

    logger.info("Phase 1: collecting vacancy URLs")
    await run_search()

    logger.info("Phase 2: downloading and parsing vacancies")
    await run_pipeline()

    logger.info("Scraper service finished")


if __name__ == "__main__":
    asyncio.run(main())
