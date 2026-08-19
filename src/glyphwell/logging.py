"""Journalisation : `logging` standard, rendu par Rich."""

import logging
from typing import TYPE_CHECKING

from rich.logging import RichHandler

from glyphwell.console import console

if TYPE_CHECKING:
    from glyphwell.config import LogLevel

__all__ = ["get_logger", "setup_logging"]

_LOGGER_NAME = "glyphwell"


def setup_logging(level: "LogLevel" = "INFO") -> None:
    """Installe un unique handler Rich sur le logger racine du projet.

    Idempotent : un second appel remplace le handler au lieu de l'empiler, ce qui évite
    les lignes dupliquées quand la CLI est invoquée depuis un test.

    Le handler écrit sur la `console` partagée du projet, et non sur une instance à lui :
    c'est ce qui permet à une ligne de journal émise pendant un `Progress` de s'insérer
    au-dessus de la barre au lieu de la hacher (cf. [console.py](console.py)).
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
    """Renvoie un logger enfant de ``glyphwell``.

    `name` est typiquement le `__name__` du module appelant ; le préfixe du paquet est
    retiré pour garder des noms courts à l'affichage.
    """
    if name is None:
        return logging.getLogger(_LOGGER_NAME)
    suffix = name.removeprefix(f"{_LOGGER_NAME}.")
    return logging.getLogger(f"{_LOGGER_NAME}.{suffix}")
