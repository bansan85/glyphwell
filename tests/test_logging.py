"""Logging: the handler must share the project's console."""

import logging

from rich.logging import RichHandler

from glyphwell.console import console
from glyphwell.logging import get_logger, setup_logging


def test_handler_writes_to_shared_console() -> None:
    """Regression: a `RichHandler` of its own made the progress bar unreadable.

    `RichHandler()` without arguments takes Rich's global console, distinct from the
    one used by subcommands. Both then track their own cursor position, and a log line
    emitted during a `Progress` ends up writing over the bar.
    """
    setup_logging("INFO")

    handlers = get_logger().handlers
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, RichHandler)
    assert handler.console is console


def test_setup_logging_is_idempotent() -> None:
    setup_logging("INFO")
    setup_logging("DEBUG")

    logger = get_logger()
    assert len(logger.handlers) == 1
    assert logger.level == logging.DEBUG
