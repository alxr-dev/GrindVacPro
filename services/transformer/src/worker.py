"""GrindVacPro — Transformer arq worker (CPU-bound: Markdown, embeddings, filtering)."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from arq.connections import RedisSettings
from markitdown import MarkItDown
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from shared.src.config import load_resume, settings
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
    # Cosine similarity via normalized dot product
    norms = np.linalg.norm(chunk_vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)  # avoid division by zero
    normalized = chunk_vectors / norms

    resume_norm_val: float = float(np.linalg.norm(_resume_vector))
    if resume_norm_val == 0:
        # Empty resume vector — cannot compute similarity; reject all
        return 0.0, None

    resume_norm = _resume_vector / resume_norm_val
    similarities: np.ndarray = np.dot(normalized, resume_norm)

    max_idx = int(np.argmax(similarities))
    return float(similarities[max_idx]), chunk_vectors[max_idx]


async def _enqueue_analyze(ctx: dict[str, Any], vacancy_id: int) -> None:
    """Send a task to the *ai_queue* via arq using the worker's Redis pool."""
    redis = ctx["redis"]
    await redis.enqueue_job(
        "analyze_vacancy",
        _queue_name="ai_queue",
        vacancy_id=vacancy_id,
    )


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
            md_result = _markitdown.convert_stream(
                io.BytesIO(vacancy.description_html.encode("utf-8"))
            )
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

        # pgvector expects format: [0.123,-0.456,...] (no spaces)
        embedding_str = "[" + ",".join(f"{x:.6f}" for x in embedding_list) + "]"
        embedding_dim = _model.get_embedding_dimension()

        try:
            await session.execute(
                text(
                    f"UPDATE vacancies SET embedding = :emb::vector({embedding_dim}) WHERE id = :vid"
                ),
                {"emb": embedding_str, "vid": vacancy_id},
            )
            await session.commit()
        except IntegrityError:
            logger.info(
                "Duplicate content_hash on commit for vacancy #%d, rejecting", vacancy_id
            )
            await session.rollback()
            await session.execute(
                update(VacancyLink)
                .where(VacancyLink.vacancy_id == vacancy_id)
                .values(status="rejected")
            )
            await session.commit()
            return

    logger.info("Vacancy #%d passed filter (sim=%.4f), enqueuing for AI", vacancy_id, max_sim)
    await _enqueue_analyze(ctx, vacancy_id)


async def on_startup(ctx: dict[str, Any]) -> None:
    """One-time initialization: load model, encode resume."""
    global _model, _resume_vector, _markitdown

    logger.info("Loading SentenceTransformer model: %s", EMBEDDING_MODEL_NAME)
    _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    logger.info("Model loaded. Embedding dimension: %d", _model.get_embedding_dimension())

    _markitdown = MarkItDown()

    try:
        resume_text = load_resume()
    except FileNotFoundError as exc:
        raise ValueError(
            f"Resume file not found — transformer cannot function without a resume. "
            f"Ensure the resume file exists at the configured path. Details: {exc}"
        ) from exc

    if resume_text.strip():
        logger.info("Encoding target resume (%d chars)", len(resume_text))
        _resume_vector = _model.encode([resume_text])[0]
        logger.info("Resume vector ready (dim=%d)", len(_resume_vector))
    else:
        raise ValueError(
            "Resume file is empty — transformer cannot function without a resume. "
            "Populate the resume file with your professional summary."
        )


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
    retry_delay = 30  # seconds — CPU-bound work needs longer recovery
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "html_queue"
    burst = False  # Keep worker running, wait for jobs
