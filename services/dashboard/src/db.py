"""GrindVacPro dashboard — database helpers."""

from sqlalchemy import text

from shared.src.database import get_sync_session_maker

_session_maker = None


def get_session():
    """Return a sync SQLAlchemy session (cached factory)."""
    global _session_maker
    if _session_maker is None:
        _session_maker = get_sync_session_maker()
    return _session_maker()


def fetch_all(query: str, params: dict | None = None) -> list[dict]:
    """Execute a raw SQL query and return list of dicts."""
    with get_session() as session:
        result = session.execute(text(query), params or {})
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result.fetchall()]


def fetch_one(query: str, params: dict | None = None) -> dict | None:
    """Execute a raw SQL query and return a single row as dict or None."""
    rows = fetch_all(query, params)
    return rows[0] if rows else None
