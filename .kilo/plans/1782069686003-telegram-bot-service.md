# Plan: Telegram Bot Service

## Goal
Deliver analyzed vacancies to user Telegram with two-step confirmation (accept/reject → confirm → reason) and store feedback in DB for later prompt tuning review.

## Architecture Decision (IMPORTANT)
The service does NOT use `CMD ["arq", "src.worker.WorkerSettings"]`. Instead:
- `CMD ["python", "-m", "src.main"]`
- `src/main.py` runs **both** aiogram polling AND arq worker in the same asyncio loop
- aiogram `dp.start_polling(bot)` runs as background task
- arq `Worker.async_run()` blocks processing jobs from `telegram_queue`
- Bot reference stored as module-level singleton, accessible by both polling handlers and job function

## Scope
- New service `telegram_bot` (aiogram 3 + arq consumer)
- DB schema migration (`infra/postgres/init.sql`)
- Config extension (`shared/src/config.py`)
- Analyzer integration (enqueue to `telegram_queue` after successful analysis)

## Non-Scope
- Multi-user support (single user only, hardcoded via env)
- Free-text reason input (stateless, no FSM → record predefined reason only)
- Admin commands or dashboards

## Data Model Changes
```sql
ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE vacancy_links ADD COLUMN IF NOT EXISTS telegram_notified BOOLEAN DEFAULT FALSE;
```

Update `vacancy_links.status` CHECK constraint to include: `'new', 'parsed', 'rejected', 'processed', 'failed', 'accepted', 'declined'`

## Callback Flow (Stateless)
Format: `vac:{vacancy_id}:{action}:{idx?}`

1. **Card** (`vac:{id}:show`) — HTML with score, linked title, company, pros, cons, `<code>` cover letter. Buttons: `[❌ Отказался] [✔️ Откликнулся]`
2. **Confirm** (`vac:{id}:cr` / `vac:{id}:ca`) — "Подтвердить {отказ/отклик}?". Buttons: `[Подтвердить] [Назад]`
3. **Reason** (`vac:{id}:rd:{idx}` / `vac:{id}:ra:{idx}`) — Save `VacancyLink.status` + `Vacancy.notes`. Show reasons:
   - *Accept*: `["Совпадение по стеку", "Интересная компания", "Хорошие условия", "Другое"]`
   - *Decline*: `["Низкий score", "Не подходит стек", "Не удалёнка", "Другое"]`

Back button always returns to step 1 (`show`). All messaging via `edit_message_text`.

## Files to Create
- `services/telegram_bot/Dockerfile` — Python 3.12-slim, copy shared + service, CMD `python -m src.main`
- `services/telegram_bot/requirements.txt` — `aiogram==3.*`
- `services/telegram_bot/src/__init__.py`
- `services/telegram_bot/src/main.py` — initialize aiogram Bot+Dispatcher, start polling as background task, run arq Worker.async_run() as main task
- `services/telegram_bot/src/worker.py` — defines `send_vacancy_notification(ctx, vacancy_data)`, `WorkerSettings`, `on_startup`/`on_shutdown` for arq
- `services/telegram_bot/src/keyboards.py` — `build_card_kb(id)`, `build_confirm_kb(id, action)`, `build_reason_kb(id, kind)`
- `services/telegram_bot/src/messages.py` — `format_card(v)`, `format_confirm(action)`, `format_reasons(kind)`, `format_thanks(reason)`
- `services/telegram_bot/src/callbacks.py` — parse `vac:*` callbacks, handle state transitions, DB writes

## Files to Modify
- `shared/src/config.py` — add `telegram_bot_token: str`, `telegram_user_id: int`
- `shared/src/models.py` — add `notes: Mapped[str | None]` to `Vacancy`; add `telegram_notified: Mapped[bool]` to `VacancyLink`
- `infra/postgres/init.sql` — add new columns, extend status CHECK
- `services/analyzer/src/worker.py` — after DB commit, enqueue to `telegram_queue`
- `docker-compose.yml` — add `telegram_bot` service (depends on postgres, redis), pass `TELEGRAM_BOT_TOKEN` and `TELEGRAM_USER_ID`

## Analyzer Integration Detail
In `_analyze_vacancy_impl`, after `session.commit()`:
```python
await ctx["arq_pool"].enqueue_job(
    "send_vacancy_notification",
    {"vacancy_id": vacancy_id},
    _queue_name="telegram_queue",
)
```
If enqueue fails → log + continue (vacancy stays `processed`, notification can be retried manually later).

## telegram_bot/src/main.py Pattern
```python
import asyncio
from aiogram import Bot, Dispatcher
from arq import Worker
from arq.connections import RedisSettings
from worker import WorkerSettings, send_vacancy_notification

_bot: Bot | None = None
_dp: Dispatcher | None = None

def get_bot() -> Bot:
    global _bot
    assert _bot is not None
    return _bot

async def main():
    global _bot, _dp
    
    _bot = Bot(token=settings.telegram_bot_token)
    _dp = Dispatcher()
    from .callbacks import router
    _dp.include_router(router)
    
    worker = Worker(
        functions=[send_vacancy_notification],
        redis_settings=RedisSettings.from_dsn(settings.redis_url),
        queue_name="telegram_queue",
        max_jobs=10,
    )
    
    # Start aiogram polling as background task
    polling_task = asyncio.create_task(_dp.start_polling(_bot))
    
    # Run arq worker (blocks forever)
    try:
        await worker.async_run()
    finally:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        await worker.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Error Handling
- Retrieve `VacancyLink` with `vacancy_id`; if missing → log + skip
- Check `telegram_notified` before sending; if true → skip (idempotency against arq retries)
- Wrap all Telegram API calls in `try/except`; on fail → log and mark job as failed
- Validate callback `vacancy_id` exists before any state change
- User must match `settings.telegram_user_id`; ignore others with `logger.warning`

## HTML Safety
Escape all DB content before insertion into `<a>`, `<code>`, and plain text:
- `html.escape(title)`, `html.escape(company_name)`, `html.escape(cover_letter)`
- Preserve `<code>` / `</code>` wrappers around cover_letter

## Validation (E2E)
1. `docker compose up --build` → all services healthy
2. Run pipeline end-to-end
3. Open Telegram → verify vacancy card arrives
4. Tap ❌ → confirm appears
5. Confirm → reason buttons appear
6. Pick reason → DB has `status='declined'` and `notes='Низкий score'`
7. Repeat accept flow

## Open Question
None. Proceed to implementation.
