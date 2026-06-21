"""GrindVacPro — Pydantic DTOs for arq task queues."""

from __future__ import annotations

from pydantic import BaseModel


class ScrapeTaskDTO(BaseModel):
    """Payload enqueued by the scraper to trigger HTML download + parsing."""

    vacancy_link_id: int


class TransformTaskDTO(BaseModel):
    """Payload enqueued by the scraper pipeline to trigger CPU-bound transform."""

    vacancy_id: int


class AnalyzeTaskDTO(BaseModel):
    """Payload enqueued by the transformer to trigger LLM analysis."""

    vacancy_id: int
