"""GrindVacPro — Telegram bot service entry point.

Runs both aiogram polling and arq worker in a single asyncio loop:
- aiogram handles user interactions (callback queries)
- arq worker processes `send_vacancy_notification` jobs from the `telegram_queue`

If TELEGRAM_BOT_TOKEN is not configured, only the arq worker starts
(notifications will be queued but not delivered).
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from arq import Worker
from arq.connections import RedisSettings

from shared.src.config import settings
from shared.src.utils.logger import get_logger

from .callbacks import router
from .worker import WorkerSettings, set_bot

logger = get_logger("telegram_bot.main")

_enable_polling: bool = False


async def main() -> None:
    """Start aiogram polling + arq worker."""
    global _enable_polling
    _enable_polling = bool(settings.telegram_bot_token) and settings.telegram_user_id != 0

    if _enable_polling:
        bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        set_bot(bot)

        dp = Dispatcher()
        dp.include_router(router)
    else:
        bot = None
        dp = None
        logger.warning(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_USER_ID not set — "
            "running arq worker only (no Telegram polling)"
        )

    worker = Worker(
        functions=WorkerSettings.functions,
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        queue_name=WorkerSettings.queue_name,
        max_jobs=WorkerSettings.max_jobs,
        on_startup=WorkerSettings.on_startup,
        on_shutdown=WorkerSettings.on_shutdown,
    )

    if _enable_polling:
        assert bot is not None and dp is not None
        polling_task = asyncio.create_task(dp.start_polling(bot))
    else:
        polling_task = None

    try:
        await worker.async_run()
    finally:
        if polling_task is not None:
            polling_task.cancel()
            try:
                await polling_task
            except asyncio.CancelledError:
                pass
        if bot is not None:
            await bot.session.close()
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
