"""GrindVacPro — Unified structured logger."""

import logging
import sys
from typing import Any

_LOGGER_NAME = "grindvac"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the ``grindvac`` namespace."""
    full_name = f"{_LOGGER_NAME}.{name}" if name else _LOGGER_NAME
    logger = logging.getLogger(full_name)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

    return logger
