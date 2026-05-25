# Copyright 2026 Binary Core LLC
# SPDX-License-Identifier: Apache-2.0

"""Structured file + console logging for BowerBot.

On ``configure_logging(settings)``:

- Bowerbot's own loggers (``bowerbot.*``) get a rotating file handler at
  the configured level (default ``INFO``) writing to
  ``~/.bowerbot/logs/bowerbot.log`` (rotated at 10 MB, keep 5 backups).
  The log directory is fixed; only verbosity and rotation are tunable.
- Console handler stays at ``WARNING`` by default so interactive use is
  not noisy; users can lower it via ``logging.console_level``.
- A session ID prefix is added to every line so a single chat session
  is easy to grep out of a multi-session log file.
- ``bowerbot`` logger is set with ``propagate=False`` so logs do not
  double-emit through the root logger.

Idempotent: callable multiple times (clears prior bowerbot handlers
before reattaching). Safe to import without configuring (just call
``configure_logging`` at startup).
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from bowerbot.config import BOWERBOT_HOME, Settings

_LOGGER_ROOT = "bowerbot"
_SESSION_ID = uuid.uuid4().hex[:12]
_SECRET_PATTERN = re.compile(
    r"(api[_-]?key|token|password|secret|auth(?:oriz)?)",
    re.IGNORECASE,
)
_MAX_SCALAR_LEN = 200  # truncate long string values in sanitized payloads


def session_id() -> str:
    """Return the current process's session ID (stable for the process)."""
    return _SESSION_ID


def configure_logging(settings: Settings) -> Path | None:
    """Wire BowerBot logging per *settings*; return the log file path or None.

    Returns ``None`` when logging is disabled in settings.
    """
    cfg = settings.logging
    root = logging.getLogger(_LOGGER_ROOT)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()
    root.propagate = False

    if not cfg.enabled:
        root.setLevel(logging.WARNING)
        root.addHandler(logging.NullHandler())
        return None

    root.setLevel(logging.DEBUG)

    log_dir = BOWERBOT_HOME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bowerbot.log"

    formatter = logging.Formatter(
        fmt=(
            "%(asctime)s.%(msecs)03d [" + _SESSION_ID + "] "
            "%(levelname)s %(name)s %(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=cfg.max_bytes,
        backupCount=cfg.backup_count,
        encoding="utf-8",
        delay=True,
    )
    file_handler.setLevel(_resolve_level(cfg.level, logging.INFO))
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(
        _resolve_level(cfg.console_level, logging.WARNING),
    )
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    root.info(
        "session-start model=%s log_file=%s level=%s",
        settings.llm.model, log_file, cfg.level,
    )
    return log_file


def sanitize(value: Any) -> Any:
    """Recursively redact secret-looking keys and truncate long scalars."""
    if isinstance(value, Mapping):
        return {
            str(k): (
                "[REDACTED]"
                if _SECRET_PATTERN.search(str(k))
                else sanitize(v)
            )
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize(v) for v in value]
    if isinstance(value, str) and len(value) > _MAX_SCALAR_LEN:
        return value[:_MAX_SCALAR_LEN] + f"...[+{len(value) - _MAX_SCALAR_LEN}]"
    return value


def _resolve_level(name: str, fallback: int) -> int:
    """Translate a config level string into the logging module's int."""
    if not name:
        return fallback
    resolved = logging.getLevelName(name.upper())
    return resolved if isinstance(resolved, int) else fallback
