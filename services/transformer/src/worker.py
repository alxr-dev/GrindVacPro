"""GrindVacPro — Transformer arq worker (CPU-bound: Markdown, embeddings, filtering)."""

from __future__ import annotations

from typing import Any

import numpy as np
from arq.connections import RedisSettings
from markitdown import MarkItDown
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, text, update

from shared.src.config import settings
from shared.src.database import get_session_maker
from shared.src.models import Vacancy, VacancyLink
from shared.src.utils.crypto import sha256_hex
from shared.src.utils.logger import get_logger

logger = get_logger("transformer.worker")

# ── Constants ────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME = "cointegrated/rubert-tiny2"
MAX_CHUNK_LENGTH = 1200
OVERLAP_LINES = 2
SIMILARITY_THRESHOLD = 0.70
EMBEDDING_DIM = 312

# ── Module-level state (populated in on_startup) ─────────────────
_model: SentenceTransformer | None = None
_resume_vector: np.ndarray | None = None
_markitdown: MarkItDown | None = None


def _chunk_markdown(text: str) -> list[str]:
    """Split Markdown text into overlapping chunks.

    Lines are accumulated up to *MAX_CHUNK_LENGTH* characters.
    Each chunk overlaps the previous by *OVERLAP_LINES* lines.
    """
    lines: list[str] = text.split("\n")
    chunks: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > MAX_CHUNK_LENGTH and current_lines:
            chunks.append("\n".join(current_lines))
            # Keep overlap lines for context continuity
            current_lines = current_lines[-OVERLAP_LINES:]
            current_len = sum(len(l) + 1 for l in current_lines)
        current_lines.append(line)
        current_len += line_len

    if current_lines:
        chunks.append("\n".join(current_lines))

    return chunks


def _encode_chunks(chunks: list[str]) -> np.ndarray:
    """Encode a list of text chunks into embedding vectors."""
    assert _model is not None
    return _model.encode(chunks, show_progress_bar=False)


def _max_similarity(chunks: list[str]) -> tuple[float, np.ndarray | None]:
    """Compute max cosine similarity between *chunks* and the resume vector.

    Returns ``(max_sim, best_vector)`` — best_vector is ``None`` if no chunks.
    """
    assert _resume_vector is not None
    if not chunks:
        return 0.0, None

    chunk_vectors = _encode_chunks(chunks)
    # Cosine similarity = 1 - cosine distance via normalized dot product
    norms = np.linalg.norm(chunk_vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)  # avoid division by zero
    normalized = chunk_vectors / norms
    resume_norm = _resume_vector / np.linalg.norm(_resume_vector)
    similarities: np.ndarray = np.dot(normalized, resume_norm)

    max_idx = int(np.argmax(similarities))
    return float(similarities[max_idx]), chunk_vectors[max_idx]


async def _enqueue_analyze(ctx: dict[str, Any], vacancy_id: int) -> None:
    """Send a task to the *ai_queue* via arq using the worker's Redis pool."""
    redis = ctx["redis"]
    await redis.enqueue_job("analyze_vacancy", vacancy_id=vacancy_id)


async def transform_vacancy(ctx: dict[str, Any], vacancy_id: int) -> None:
    """Process a single vacancy: dedup → chunk → embed → filter → enqueue."""
    assert _model is not None
    assert _resume_vector is not None
    assert _markitdown is not None

    maker = get_session_maker()

    async with maker() as session:
        # Fetch the vacancy
        result = await session.execute(
            select(Vacancy).where(Vacancy.id == vacancy_id)
        )
        vacancy = result.scalar_one_or_none()

        if vacancy is None:
            logger.warning("Vacancy #%d not found, skipping", vacancy_id)
            return

        # ── Step 1: HTML → Markdown ──────────────────────────────
        try:
            md_result = _markitdown.convert(vacancy.description_html)
            markdown_text = md_result.text_content
        except Exception as exc:
            logger.error("MarkItDown failed for vacancy #%d: %s", vacancy_id, exc)
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(status="failed")
            )
            await session.commit()
            return

        # ── Step 2: Deduplication via SHA-256 ────────────────────
        content_hash = sha256_hex(markdown_text)

        # Check if this hash already exists (another vacancy with same content)
        existing = await session.execute(
            select(Vacancy).where(Vacancy.content_hash == content_hash)
        )
        duplicate = existing.scalar_one_or_none()

        if duplicate is not None and duplicate.id != vacancy.id:
            logger.info(
                "Duplicate content: vacancy #%d matches #%d, rejecting",
                vacancy_id,
                duplicate.id,
            )
            # Re-link the vacancy_link to the existing vacancy
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy.id)
                .values(vacancy_id=duplicate.id, status="rejected")
            )
            await session.commit()
            return

        # Update vacancy with markdown and real content_hash
        vacancy.description_markdown = markdown_text
        vacancy.content_hash = content_hash
        await session.flush()

        # ── Step 3: Chunking ─────────────────────────────────────
        chunks = _chunk_markdown(markdown_text)
        if not chunks:
            logger.warning("Vacancy #%d produced no chunks, rejecting", vacancy_id)
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(status="rejected")
            )
            await session.commit()
            return

        # ── Step 4: MaxSim filtering ─────────────────────────────
        max_sim, best_vector = _max_similarity(chunks)

        logger.info(
            "Vacancy #%d: %d chunks, max_similarity=%.4f",
            vacancy_id,
            len(chunks),
            max_sim,
        )

        if max_sim < SIMILARITY_THRESHOLD:
            logger.info(
                "Vacancy #%d rejected (%.4f < %.2f)", vacancy_id, max_sim, SIMILARITY_THRESHOLD
            )
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(status="rejected")
            )
            await session.commit()
            return

        # ── Step 5: Save best embedding and enqueue for AI ───────
        assert best_vector is not None
        embedding_list: list[float] = best_vector.tolist()

        # Store embedding via raw SQL to properly handle pgvector type
        await session.execute(
            text(
                "UPDATE vacancies SET embedding = :emb WHERE id = :vid"
            ),
            {"emb": str(embedding_list), "vid": vacancy_id},
        )
        await session.commit()

    logger.info("Vacancy #%d passed filter (sim=%.4f), enqueuing for AI", vacancy_id, max_sim)
    await _enqueue_analyze(ctx, vacancy_id)


async def on_startup(ctx: dict[str, Any]) -> None:
    """One-time initialization: load model, encode resume."""
    global _model, _resume_vector, _markitdown

    logger.info("Loading SentenceTransformer model: %s", EMBEDDING_MODEL_NAME)
    _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    logger.info("Model loaded. Embedding dimension: %d", _model.get_sentence_embedding_dimension())

    _markitdown = MarkItDown()

    if settings.target_resume:
        logger.info("Encoding target resume…")
        _resume_vector = _model.encode([settings.target_resume])[0]
        logger.info("Resume vector ready (dim=%d)", len(_resume_vector))
    else:
        logger.warning("TARGET_RESUME is empty — all vacancies will pass the filter")
        _resume_vector = np.zeros(EMBEDDING_DIM, dtype=np.float32)


async def on_shutdown(ctx: dict[str, Any]) -> None:
    """Cleanup resources."""
    logger.info("Transformer worker shutting down")


class WorkerSettings:
    """arq worker configuration."""

    functions = [transform_vacancy]
    on_startup = on_startup
    on_shutdown = on_shutdown
    max_jobs = 1  # CPU-bound: one job at a time
    max_retries = 3
    retry_delay = 5  # seconds
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "html_queue"
