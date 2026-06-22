"""GrindVacPro — Analyzer arq worker (Network I/O: LLM analysis)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from urllib.parse import urlparse

from arq.connections import RedisSettings
from openai import AsyncOpenAI
from sqlalchemy import select, update

from shared.src.config import load_resume, settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink
from shared.src.utils.logger import get_logger

from src.prompts import SYSTEM_PROMPT

logger = get_logger("analyzer.worker")


def _clean_llm_json(raw: str) -> str:
    """Strip markdown code fences and whitespace from LLM JSON response.

    LLM models sometimes wrap their JSON in ```json ... ``` blocks.
    This function extracts the raw JSON string.
    """
    text = raw.strip()
    # Strip ```json ... ``` fences
    if text.startswith("```"):
        # Remove first line (```json or ```)
        lines = text.split("\n")
        # Remove first and last lines if they are fences
        if lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _try_fix_json(raw: str) -> dict[str, Any] | None:
    """Attempt to fix a truncated JSON string from LLM response.

    Tries adding missing closing braces/brackets and parsing again.
    Returns the parsed dict on success, None on failure.
    """
    # Try adding closing braces/brackets
    for suffix in ["}", "}]", "}]}"]:
        try:
            candidate = raw.rstrip() + suffix
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


# ── Module-level state ───────────────────────────────────────────
_openai_client: AsyncOpenAI | None = None
_resume_text: str = ""
_llm_semaphore = asyncio.Semaphore(5)  # cap concurrent LLM calls


async def analyze_vacancy(ctx: dict[str, Any], vacancy_id: int) -> None:
    """Analyze a vacancy via LLM and store the structured result."""
    assert _openai_client is not None

    async with _llm_semaphore:
        await _analyze_vacancy_impl(ctx, vacancy_id)


async def _analyze_vacancy_impl(ctx: dict[str, Any], vacancy_id: int) -> None:
    """Implementation of vacancy analysis (runs inside semaphore)."""
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
                        f"Резюме кандидата:\n{_resume_text}\n\n"
                        f"---\n\n"
                        f"Вакансия: {vacancy.title}\n"
                        f"Компания: {vacancy.company_name}\n"
                        f"Описание:\n{markdown}"
                    ),
                },
            ],
            max_tokens=1024,
            temperature=0,
        )
        # Some reasoning models return content in the "reasoning" field
        # instead of "content". Try both.
        message = response.choices[0].message
        raw_content = message.content
        if raw_content is None and hasattr(message, "reasoning") and message.reasoning:
            raw_content = message.reasoning
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
        cleaned = _clean_llm_json(raw_content)
        analysis: dict[str, Any] = json.loads(cleaned)
        score = max(0, min(100, int(analysis["score"])))
        pros = list(analysis["pros"])
        cons = list(analysis["cons"])
        cover_letter = str(analysis["cover_letter"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        # Attempt to fix truncated JSON (missing closing brace)
        fixed = _try_fix_json(_clean_llm_json(raw_content))
        if fixed is not None:
            try:
                analysis = fixed
                score = max(0, min(100, int(analysis["score"])))
                pros = list(analysis["pros"])
                cons = list(analysis["cons"])
                cover_letter = str(analysis["cover_letter"])
                logger.info("Fixed truncated JSON for vacancy #%d", vacancy_id)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc2:
                safe_raw = raw_content[:200].replace("\n", " ").replace("\r", " ")
                logger.error(
                    "Failed to parse LLM response for vacancy #%d (fix attempt failed): %s\nRaw: %s",
                    vacancy_id,
                    exc2,
                    safe_raw,
                )
                async with maker() as session:
                    await session.execute(
                        update(VacancyLink)
                        .where(VacancyLink.vacancy_id == vacancy_id)
                        .values(status="failed")
                    )
                    await session.commit()
                return
        else:
            # Sanitize: replace control chars to prevent log injection
            safe_raw = raw_content[:200].replace("\n", " ").replace("\r", " ")
            logger.error(
                "Failed to parse LLM response for vacancy #%d: %s\nRaw: %s",
                vacancy_id,
                exc,
                safe_raw,
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
    """Initialize the async OpenAI client and load resume."""
    global _openai_client, _resume_text
    _openai_client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=120.0,  # 2 minutes max per LLM call
    )
    # Load resume text for LLM prompts
    try:
        _resume_text = load_resume()
        logger.info("Resume loaded (%d chars)", len(_resume_text))
    except FileNotFoundError as exc:
        raise ValueError(
            f"Resume file not found — analyzer cannot function without a resume. "
            f"Details: {exc}"
        ) from exc
    # Log only scheme+host to avoid leaking credentials from userinfo
    parsed = urlparse(settings.openai_base_url)
    safe_base = f"{parsed.scheme}://{parsed.hostname}" if parsed.hostname else settings.openai_base_url
    logger.info(
        "OpenAI client ready (model=%s, base_url=%s)",
        settings.openai_model_name,
        safe_base,
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
    max_jobs = 10  # Network I/O: moderate concurrency to avoid rate limits
    max_retries = 3
    retry_delay = 10  # seconds
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "ai_queue"
    burst = False  # Keep worker running, wait for jobs
