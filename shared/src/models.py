"""GrindVacPro — SQLAlchemy 2.0 ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Boolean,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


class Vacancy(Base):
    """Vacancy entity — parsed and enriched job posting."""

    __tablename__ = "vacancies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description_html: Mapped[str] = mapped_column(Text, nullable=False)
    description_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # embedding is managed raw via SQL (pgvector); not mapped to keep model simple
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ai_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP")
    )

    links: Mapped[list[VacancyLink]] = relationship(
        "VacancyLink", back_populates="vacancy", cascade="all, delete-orphan"
    )


class VacancyLink(Base):
    """Tracked URL pointing to a vacancy on a job platform."""

    __tablename__ = "vacancy_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vacancy_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("vacancies.id", ondelete="CASCADE"), nullable=True
    )
    url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default="new")
    telegram_notified: Mapped[bool] = mapped_column(Boolean, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP")
    )

    vacancy: Mapped[Vacancy | None] = relationship("Vacancy", back_populates="links")
