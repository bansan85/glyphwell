"""Logging: standard `logging`, rendered by Rich."""

import logging
from typing import TYPE_CHECKING

from rich.logging import RichHandler

from glyphwell.console import console

if TYPE_CHECKING:
    from glyphwell.config import LogLevel

__all__ = ["get_logger", "setup_logging"]

_LOGGER_NAME = "glyphwell"


def setup_logging(level: "LogLevel" = "INFO") -> None:
    """Installs a single Rich handler on the project's root logger.

    Idempotent: a second call replaces the handler instead of stacking it, which avoids
    duplicated lines when the CLI is invoked from within a test.

    The handler writes to the project's shared `console`, not to an instance of its own:
    that's what lets a log line emitted during a `Progress` insert itself above the bar
    instead of slicing through it (see [console.py](console.py)).
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False

    handler = RichHandler(
        console=console, rich_tracebacks=True, show_path=False, omit_repeated_times=False
    )
    handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    logger.addHandler(handler)


def get_logger(name: str | None = None) -> logging.Logger:
    """Returns a child logger of ``glyphwell``.

    `name` is typically the calling module's `__name__`; the package prefix is
    stripped to keep displayed names short.
    """
    if name is None:
        return logging.getLogger(_LOGGER_NAME)
    suffix = name.removeprefix(f"{_LOGGER_NAME}.")
    return logging.getLogger(f"{_LOGGER_NAME}.{suffix}")
