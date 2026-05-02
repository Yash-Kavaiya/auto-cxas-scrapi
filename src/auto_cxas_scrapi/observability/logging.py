"""Structured logging helpers."""
from __future__ import annotations

import logging
import os

from rich.logging import RichHandler


def configure_logging(level: str | None = None) -> logging.Logger:
    log_level = level or os.environ.get("AUTO_CXAS_LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
    )
    return logging.getLogger("auto_cxas_scrapi")


def get_logger(name: str = "auto_cxas_scrapi") -> logging.Logger:
    return logging.getLogger(name)
