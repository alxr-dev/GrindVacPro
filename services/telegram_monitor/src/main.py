"""GrindVacPro — Telegram monitor service entry point."""

import asyncio
import sys

from shared.src.config import settings
from shared.src.utils.logger import get_logger

from .client import init_client
from .parser import load_keywords, load_targets, parse_historical, setup_handlers

logger = get_logger("telegram_monitor.main")


async def main() -> None:
    """Run Telegram monitoring: historical parse + online monitoring."""
    # Validate Telethon configuration
    if settings.telethon_api_id == 0:
        logger.error("TELETHON_API_ID is not configured")
        sys.exit(1)
    if not settings.telethon_api_hash:
        logger.error("TELETHON_API_HASH is not configured")
        sys.exit(1)

    logger.info("Telegram monitor service starting")

    # Initialize client
    await init_client()
    from .client import get_client
    client = get_client()

    # Load configuration
    positive_keywords, negative_keywords = load_keywords()
    if not positive_keywords:
        logger.warning("No positive keywords loaded, monitor will have no matches")

    targets = load_targets()
    if not targets:
        logger.warning("No monitoring targets loaded")

    # Phase 1: Parse historical messages (last 2 days)
    if targets:
        logger.info("Phase 1: Parsing historical messages (today and yesterday)")
        saved = await parse_historical(client, targets, positive_keywords, negative_keywords)
        logger.info("Historical parse complete: %d vacancies saved", saved)

    # Phase 2: Setup online handlers
    if targets:
        logger.info("Phase 2: Setting up online monitoring handlers")
        setup_handlers(client, targets, positive_keywords, negative_keywords)

    # Run until disconnected
    logger.info("Telegram monitor running - listening for new messages")
    try:
        await client.run_until_disconnected()
    except KeyboardInterrupt:
        logger.info("Shutting down telegram monitor")
    finally:
        await client.disconnect()
        logger.info("Telegram client disconnected")


if __name__ == "__main__":
    asyncio.run(main())