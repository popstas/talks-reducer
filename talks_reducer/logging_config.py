"""Helpers for configuring Talks Reducer logging behaviour."""

from __future__ import annotations

import logging
import os
from typing import Mapping, Optional

__all__ = ["configure_logging_from_env"]

_LOGGER = logging.getLogger(__name__)
_ENV_VAR = "LOG_LEVEL"


def _resolve_log_level(value: str) -> Optional[int]:
    """Translate a string environment value into a logging level."""

    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        level = logging.getLevelName(text.upper())
        if isinstance(level, int):
            return level
    return None


def configure_logging_from_env(env: Optional[Mapping[str, str]] = None) -> None:
    """Configure the root logger based on the ``LOG_LEVEL`` environment variable."""

    mapping: Mapping[str, str]
    if env is None:
        mapping = os.environ
    else:
        mapping = env
    raw_value = mapping.get(_ENV_VAR)
    if not raw_value:
        return
    level = _resolve_log_level(raw_value)
    if level is None:
        _LOGGER.warning("Ignoring invalid LOG_LEVEL value: %r", raw_value)
        return
    logging.basicConfig(level=level)
    logging.getLogger().setLevel(level)
    _LOGGER.debug(
        "Configured logging level from %s=%s (resolved to %s)",
        _ENV_VAR,
        raw_value,
        level,
    )
