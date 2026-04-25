
"""Lightweight logging helper used across the desktop app.

This centralises logging configuration so every module just calls
``get_logger(__name__)`` and receives a logger that writes to both the
console and a rotating log file under ``logs/app``.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_ROOT_LOGGER_NAME = "wejawi"
_FILE_NAME = "app.log"
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
_BACKUPS = 3


def _ensure_root_logger() -> logging.Logger:
    root = logging.getLogger(_ROOT_LOGGER_NAME)
    if root.handlers:
        return root

    root.setLevel(logging.INFO)

    # Place logs next to existing JSONL job logs so everything is grouped.
    base = Path(__file__).resolve().parent.parent
    log_dir = base / "logs" / "app"
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")

    file_handler = RotatingFileHandler(
        log_dir / _FILE_NAME,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    root.addHandler(file_handler)
    root.addHandler(stream_handler)

    return root


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a configured logger, creating child loggers as needed."""

    root = _ensure_root_logger()
    if not name or name == _ROOT_LOGGER_NAME:
        return root
    return root.getChild(name)


__all__ = ["get_logger"]
