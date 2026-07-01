"""GrindVacPro — Telethon client singleton management."""

from __future__ import annotations

from telethon import TelegramClient

from shared.src.config import settings
from shared.src.utils.logger import get_logger

logger = get_logger("telegram_monitor.client")

# Module-level singleton
_client: TelegramClient | None = None


def get_client() -> TelegramClient:
    """Return the initialized Telethon client singleton."""
    assert _client is not None, "Telethon client not initialized"
    return _client


async def init_client() -> None:
    """Initialize and connect the Telethon client."""
    global _client

    if settings.telethon_api_id == 0 or not settings.telethon_api_hash:
        raise ValueError(
            "TELETHON_API_ID and TELETHON_API_HASH must be configured"
        )

    _client = TelegramClient(
        settings.telethon_session,
        settings.telethon_api_id,
        settings.telethon_api_hash,
    )

    await _client.connect()
    logger.info("Telethon client initialized and connected")