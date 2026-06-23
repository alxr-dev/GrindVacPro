"""GrindVacPro — Telegram bot arq worker (send notifications)."""

from __future__ import annotations

from typing import Any

from aiogram import Bot
from arq.connections import RedisSettings
from sqlalchemy import select, update

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink
from shared.src.utils.logger import get_logger

from .messages import format_card

logger = get_logger("telegram_bot.worker")

# ── Module-level state ───────────────────────────────────────────
_bot: Bot | None = None


def get_bot() -> Bot:
    """Return initialized Bot singleton."""
    assert _bot is not None, "Bot is not initialized"
    return _bot


def set_bot(bot: Bot) -> None:
    """Set the Bot singleton (called from main.py)."""
    global _bot
    _bot = bot


async def on_startup(ctx: dict[str, Any]) -> None:
    """Initialize shared state (no Redis pool needed for Telegram API)."""
    logger.info("Telegram bot worker started")


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Cleanup on worker shutdown."""
    logger.info("Telegram bot worker shutting down")


async def send_vacancy_notification(ctx: dict[str, Any], vacancy_data: dict[str, Any]) -> None:
    """Send vacancy card to the configured Telegram user."""
    vacancy_id: int = vacancy_data["vacancy_id"]

    if _bot is None:
        logger.warning(
            "Bot not initialized — skipping notification for vacancy %s", vacancy_id
        )
        return

    bot = _bot

    maker = get_session_maker()
    async with maker() as session:
        result = await session.execute(
            select(VacancyLink).where(VacancyLink.vacancy_id == vacancy_id)
        )
        link = result.scalar_one_or_none()
        if link is None:
            logger.warning("VacancyLink for vacancy_id=%d not found", vacancy_id)
            return
        if link.telegram_notified:
            logger.info("Vacancy %d already notified, skip", vacancy_id)
            return

        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()
        if vacancy is None or vacancy.ai_analysis is None:
            logger.warning("Vacancy %d has no AI analysis, skip notification", vacancy_id)
            return

        analysis = vacancy.ai_analysis
        text = format_card(
            title=vacancy.title,
            company=vacancy.company_name,
            url=link.url,
            score=vacancy.ai_score or 0,
            pros=analysis.get("pros", []),
            cons=analysis.get("cons", []),
            cover_letter=analysis.get("cover_letter", ""),
        )

    try:
        await bot.send_message(
            chat_id=settings.telegram_user_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        async with maker() as session:
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(telegram_notified=True)
            )
            await session.commit()
        logger.info("Notification sent for vacancy %d", vacancy_id)
    except Exception as exc:
        logger.error("Failed to send notification for vacancy %d: %s", vacancy_id, exc)
        raise


class WorkerSettings:
    """arq worker configuration for telegram bot."""

    functions = [send_vacancy_notification]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 10
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "telegram_queue"
    burst = False
