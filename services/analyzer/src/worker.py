"""GrindVacPro — Analyzer arq worker (Network I/O: LLM analysis)."""

from __future__ import annotations

import json
from typing import Any

from arq.connections import RedisSettings
from openai import AsyncOpenAI
from sqlalchemy import select, update

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink
from shared.src.utils.logger import get_logger

from src.prompts import SYSTEM_PROMPT

logger = get_logger("analyzer.worker")

# ── Module-level state ───────────────────────────────────────────
_openai_client: AsyncOpenAI | None = None


async def analyze_vacancy(ctx: dict[str, Any], vacancy_id: int) -> None:
    """Analyze a vacancy via LLM and store the structured result."""
    assert _openai_client is not None

    maker = get_session_maker()

    async with maker() as session:
        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()

        if vacancy is None:
            logger.warning("Vacancy #%d not found, skipping", vacancy_id)
            return

        markdown = vacancy.description_markdown or vacancy.description_html
        if not markdown:
            logger.warning("Vacancy #%d has no content to analyze", vacancy_id)
            return

    # ── Call LLM ─────────────────────────────────────────────────
    try:
        response = await _openai_client.chat.completions.create(
            model=settings.openai_model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Вакансия: {vacancy.title}\n"
                        f"Компания: {vacancy.company_name}\n"
                        f"Описание:\n{markdown}"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=2048,
        )
        raw_content = response.choices[0].message.content
        if raw_content is None:
            raise ValueError("Empty response from LLM")
    except Exception as exc:
        logger.error("LLM call failed for vacancy #%d: %s", vacancy_id, exc)
        async with maker() as session:
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(status="failed")
            )
            await session.commit()
        return

    # ── Parse JSON response ───────────────────────────────────────
    try:
        analysis: dict[str, Any] = json.loads(raw_content)
        score = max(0, min(100, int(analysis["score"])))
        pros = list(analysis["pros"])
        cons = list(analysis["cons"])
        cover_letter = str(analysis["cover_letter"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        logger.error(
            "Failed to parse LLM response for vacancy #%d: %s\nRaw: %s",
            vacancy_id,
            exc,
            raw_content[:500],
        )
        async with maker() as session:
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(status="failed")
            )
            await session.commit()
        return

    # ── Store results ─────────────────────────────────────────────
    ai_analysis = {
        "score": score,
        "pros": pros,
        "cons": cons,
        "cover_letter": cover_letter,
    }

    async with maker() as session:
        await session.execute(
            update(Vacancy)
            .where(Vacancy.id == vacancy_id)
            .values(ai_score=score, ai_analysis=ai_analysis)
        )
        await session.execute(
            update(VacancyLink)
            .where(VacancyLink.vacancy_id == vacancy_id)
            .values(status="processed")
        )
        await session.commit()

    logger.info(
        "Vacancy #%d analyzed: score=%d, pros=%d, cons=%d",
        vacancy_id,
        score,
        len(pros),
        len(cons),
    )


async def on_startup(ctx: dict[str, Any]) -> None:
    """Initialize the async OpenAI client."""
    global _openai_client
    _openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
    )
    logger.info(
        "OpenAI client ready (model=%s, base_url=%s)",
        settings.openai_model_name,
        settings.openai_base_url,
    )


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Close the OpenAI client."""
    global _openai_client
    if _openai_client is not None:
        await _openai_client.close()
    logger.info("Analyzer worker shutting down")


class WorkerSettings:
    """arq worker configuration."""

    functions = [analyze_vacancy]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 15  # Network I/O: high concurrency
    max_retries = 3
    retry_delay = 10  # seconds
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "ai_queue"
