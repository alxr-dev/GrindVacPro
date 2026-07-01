"""GrindVacPro — Telegram vacancy storage and queue integration."""

from __future__ import annotations

from arq import create_pool
from arq.connections import RedisSettings
from sqlalchemy import select
from telethon.tl.custom import Message

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink
from shared.src.utils.logger import get_logger

logger = get_logger("telegram_monitor.storage")


def _get_message_url(message: Message, chat_title: str) -> str:
    """Generate a Telegram message URL.

    Uses the chat username if available, otherwise falls back to the private
    chat format with chat_id.

    Args:
        message: Telethon Message object.
        chat_title: Title or username of the chat for fallback.

    Returns:
        Telegram message URL string.
    """
    chat_id = message.chat_id

    # Try to get username from message.chat if available
    chat = message.chat
    if chat and hasattr(chat, "username") and chat.username:
        return f"https://t.me/{chat.username}/{message.id}"

    # Private chat format: https://t.me/c/CHAT_ID/MESSAGE_ID
    # For supergroups/channels, chat_id is -100... and we need to strip -100
    if chat_id:
        adjusted_id = _adjust_chat_id_for_url(chat_id)
        return f"https://t.me/c/{adjusted_id}/{message.id}"

    # Fallback
    return f"https://t.me/{chat_title}/{message.id}"


def _adjust_chat_id_for_url(chat_id: int) -> int:
    """Adjust chat_id for t.me/c/ links.

    Telegram supergroup/channel IDs come as -100... in Telethon.
    For t.me/c links we need just the numeric ID without prefixes.

    Examples:
        -1001234567890 → 1234567890
        -12345 → 12345
    """
    if chat_id < 0:
        # For supergroups: -1001234567890 -> 1234567890
        # The format -100ID means we need to strip the 100
        if chat_id <= -1000000000000:
            return int(str(abs(chat_id))[2:])  # Strip "100"
        return abs(chat_id)

    return chat_id


async def save_vacancy_from_message(
    message: Message,
    chat_title: str,
) -> int | None:
    """Save a vacancy from a Telegram message and enqueue for transformation.

    Uses a temporary content_hash - transformer will compute the real hash
    from markdown and update it.

    Args:
        message: Telegram message containing vacancy info.
        chat_title: Title of the source chat/channel.

    Returns:
        Vacancy ID if successfully saved, None otherwise.
    """
    url = _get_message_url(message, chat_title)
    text = message.text or ""

    # Check for duplicate URL
    maker = get_session_maker()
    async with maker() as session:
        result = await session.execute(
            select(VacancyLink).where(VacancyLink.url == url)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            logger.debug("URL already exists: %s", url)
            return None

        # Create VacancyLink
        link = VacancyLink(
            url=url,
            platform="tg",
            status="new",
        )
        session.add(link)
        await session.flush()

        # Create Vacancy with temporary content_hash (will be updated by transformer)
        vacancy = Vacancy(
            platform="tg",
            title=_extract_title(text),
            company_name=chat_title,
            description_html=text,
            content_hash=f"pending_{link.id}",
        )
        session.add(vacancy)
        await session.flush()

        # Link them
        link.vacancy_id = vacancy.id

        await session.commit()

        logger.info(
            "Saved vacancy #%d from chat '%s': %s",
            vacancy.id,
            chat_title,
            vacancy.title,
        )

        # Enqueue to html_queue for transformation
        await _enqueue_transform(vacancy.id)

        return vacancy.id


async def _enqueue_transform(vacancy_id: int) -> None:
    """Enqueue a vacancy for transformation via arq.

    Args:
        vacancy_id: ID of the vacancy to transform.
    """
    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        await arq_pool.enqueue_job(
            "transform_vacancy",
            vacancy_id,
            _queue_name="html_queue",
        )
        logger.info("Enqueued vacancy #%d to html_queue", vacancy_id)
    except Exception as exc:
        logger.error("Failed to enqueue vacancy #%d: %s", vacancy_id, exc)
    finally:
        await arq_pool.close()


def _extract_title(text: str) -> str:
    """Extract a title from message text.

    Takes the first non-empty line as the title.

    Args:
        text: Full message text.

    Returns:
        Extracted title (truncated to 255 chars).
    """
    lines = text.strip().split("\n")
    for line in lines:
        line = line.strip()
        if line and len(line) > 5:  # At least a meaningful fragment
            return line[:255]
    return "Telegram Vacancy"