"""GrindVacPro — Telegram monitor service."""

from .client import get_client, init_client

__all__ = [
    "get_client",
    "init_client",
]