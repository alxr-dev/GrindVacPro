"""GrindVacPro — Telegram message parser and loader."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telethon import events

from shared.src.utils.logger import get_logger

logger = get_logger("telegram_monitor.parser")

# Paths for monitoring configuration - same as scraper uses ./services/...
KEYWORDS_PATH = Path(__file__).resolve().parent.parent / "data" / "keywords.txt"
TARGETS_PATH = Path(__file__).resolve().parent.parent / "data" / "monitoring_targets.txt"


def load_keywords() -> tuple[list[str], list[str]]:
    """Load keywords from file.

    Returns:
        Tuple of (positive_keywords, negative_keywords).
        Negative keywords start with '!' prefix.
    """
    positive: list[str] = []
    negative: list[str] = []

    if not KEYWORDS_PATH.exists():
        logger.warning("Keywords file not found: %s", KEYWORDS_PATH)
        return positive, negative

    with KEYWORDS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("!"):
                negative.append(line[1:].lower())
            else:
                positive.append(line.lower())

    logger.info(
        "Loaded %d positive and %d negative keywords",
        len(positive),
        len(negative),
    )
    return positive, negative


def load_targets() -> list[Any]:
    """Load monitoring targets (channels/chats) from file.

    Supports:
    - Integer IDs (e.g., -1001234567890)
    - Usernames with or without @ prefix (e.g., @jobs_channel or jobs_channel)

    Returns:
        List of target identifiers for Telethon.
    """
    targets: list[Any] = []

    if not TARGETS_PATH.exists():
        logger.warning("Targets file not found: %s", TARGETS_PATH)
        return targets

    with TARGETS_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Try to parse as integer ID
            if line.lstrip("-").isdigit():
                targets.append(int(line))
            else:
                # Username: remove @ prefix if present
                if line.startswith("@"):
                    line = line[1:]
                targets.append(line)

    logger.info("Loaded %d monitoring targets", len(targets))
    return targets


def matches_keywords(text: str, positive: list[str], negative: list[str]) -> bool:
    """Check if text matches positive keywords and doesn't match negative ones.

    Args:
        text: Message text to check.
        positive: List of positive keywords (must contain at least one).
        negative: List of negative keywords (rejects if contains any).

    Returns:
        True if message should be parsed, False otherwise.
    """
    text_lower = text.lower()

    # Check negative keywords first (reject if any match)
    for neg in negative:
        if neg in text_lower:
            return False

    # Check positive keywords (accept if any match)
    for pos in positive:
        if pos in text_lower:
            return True

    return False


async def _rate_limit_delay() -> None:
    """Apply rate limiting delay between Telegram API requests."""
    await asyncio.sleep(0.3)  # Light delay to avoid overwhelming Telegram API


async def parse_historical(
    client,
    targets: list[Any],
    positive: list[str],
    negative: list[str],
) -> int:
    """Parse messages from the last 2 days (today and yesterday).

    Args:
        client: Telethon TelegramClient instance.
        targets: List of channel/chat identifiers.
        positive: Positive keywords for filtering.
        negative: Negative keywords for exclusion.

    Returns:
        Number of vacancies saved.
    """
    from .storage import save_vacancy_from_message

    # Calculate date range: yesterday and today
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start = today_start - timedelta(days=1)

    saved_count = 0

    for target in targets:
        try:
            entity = await client.get_entity(target)
            chat_title = (
                getattr(entity, "title", None)
                or getattr(entity, "username", None)
                or str(target)
            )

            logger.info("Parsing historical messages from target: %s", chat_title)

            # Get messages from yesterday onwards
            async for message in client.iter_messages(
                entity,
                offset_date=yesterday_start,
                reverse=True,  # Oldest first, stop at yesterday boundary
            ):
                if not message.text:
                    continue

                if not matches_keywords(message.text, positive, negative):
                    continue

                vacancy_id = await save_vacancy_from_message(
                    message=message,
                    chat_title=chat_title,
                )

                if vacancy_id:
                    saved_count += 1

                await _rate_limit_delay()

        except Exception as exc:
            logger.error("Failed to parse target %s: %s", target, exc)

    return saved_count


def setup_handlers(
    client,
    targets: list[Any],
    positive: list[str],
    negative: list[str],
) -> None:
    """Setup Telethon event handlers for online monitoring.

    Args:
        client: Telethon TelegramClient instance.
        targets: List of channel/chat identifiers to monitor.
        positive: Positive keywords for filtering.
        negative: Negative keywords for exclusion.
    """

    @client.on(events.NewMessage(chats=targets))
    async def handle_new_message(event):
        from .storage import save_vacancy_from_message

        message = event.message
        if not message.text:
            return

        # Check keywords
        if not matches_keywords(message.text, positive, negative):
            return

        # Get chat info
        chat = await event.get_chat()
        chat_title = (
            getattr(chat, "title", None)
            or getattr(chat, "username", None)
            or str(chat.id)
        )

        await save_vacancy_from_message(
            message=message,
            chat_title=chat_title,
        )