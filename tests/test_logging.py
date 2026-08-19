"""Journalisation : le handler doit partager la console du projet."""

import logging

from rich.logging import RichHandler

from glyphwell.console import console
from glyphwell.logging import get_logger, setup_logging


def test_le_handler_ecrit_sur_la_console_partagee() -> None:
    """Régression : un `RichHandler` à lui rendait la barre de progression illisible.

    `RichHandler()` sans argument prend la console globale de Rich, distincte de celle
    des sous-commandes. Les deux tiennent alors leur propre position de curseur, et une
    ligne de journal émise pendant un `Progress` vient s'écrire par-dessus la barre.
    """
    setup_logging("INFO")

    handlers = get_logger().handlers
    assert len(handlers) == 1
    handler = handlers[0]
    assert isinstance(handler, RichHandler)
    assert handler.console is console


def test_setup_logging_est_idempotent() -> None:
    setup_logging("INFO")
    setup_logging("DEBUG")

    logger = get_logger()
    assert len(logger.handlers) == 1
    assert logger.level == logging.DEBUG
