"""GrindVacPro — Async database engine and session factory (SQLAlchemy 2.0)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from shared.src.config import settings

_engine: AsyncEngine | None = None
_async_session_maker: async_sessionmaker[AsyncSession] | None = None
_session_maker: sessionmaker | None = None


def _get_engine() -> AsyncEngine:
    """Lazily create and cache the async engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=20,
            echo=False,
        )
    return _engine


def get_session_maker() -> async_sessionmaker[AsyncSession]:
    """Return a cached async session factory."""
    global _async_session_maker
    if _async_session_maker is None:
        engine = _get_engine()
        _async_session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _async_session_maker


def get_sync_session_maker() -> sessionmaker:
    """Return a cached sync session factory (for dashboard / scripts)."""
    global _session_maker
    if _session_maker is None:
        sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
        engine = create_engine(
            sync_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
            echo=False,
        )
        _session_maker = sessionmaker(
            engine,
            expire_on_commit=False,
        )
    return _session_maker
