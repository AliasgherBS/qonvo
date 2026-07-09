"""Structured JSON logging via loguru (DESIGN.md §12.4)."""

from __future__ import annotations

import sys

from loguru import logger

from app.core.config import settings

_configured = False


def configure_logging() -> None:
    """Install a single JSON sink. Idempotent."""
    global _configured
    if _configured:
        return
    logger.remove()
    logger.add(
        sys.stdout,
        level=settings.log_level.upper(),
        serialize=True,
        backtrace=False,
        diagnose=False,
        enqueue=True,
    )
    _configured = True


__all__ = ["configure_logging", "logger"]
