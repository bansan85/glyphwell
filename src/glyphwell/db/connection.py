"""Ouverture des connexions SQLite.

Un seul endroit configure les PRAGMA : le mode WAL est indispensable ici, car le moteur de
recherche écrit un résultat par fenêtre pendant qu'une autre commande (``db status``,
``search status``) peut lire la base.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from glyphwell.errors import DatabaseError
from glyphwell.logging import get_logger

__all__ = ["connect", "open_connection"]

_log = get_logger(__name__)

# 30 s : un import de dataset IMDb tient le verrou d'écriture un certain temps.
_BUSY_TIMEOUT_MS = 30_000


def open_connection(path: Path, *, create: bool = False) -> sqlite3.Connection:
    """Ouvre la base et applique les PRAGMA du projet.

    Args:
        path: chemin du fichier SQLite.
        create: si faux, l'absence du fichier est une erreur — on évite de créer
            silencieusement une base vide quand l'utilisateur s'est trompé de chemin.

    Raises:
        DatabaseError: base absente alors que `create` est faux, ou échec d'ouverture.
    """
    if not create and not path.exists():
        message = f"base introuvable : {path}. Lancer `glyphwell db init` d'abord."
        raise DatabaseError(message)

    if create:
        path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    except sqlite3.Error as exc:
        message = f"impossible d'ouvrir {path} : {exc}"
        raise DatabaseError(message) from exc

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA temp_store = MEMORY")
    _log.debug("base ouverte : %s", path)
    return conn


@contextmanager
def connect(path: Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    """Contextmanager autour de `open_connection`, qui garantit la fermeture.

    `isolation_level=None` désactive l'autocommit implicite de sqlite3 : les transactions
    sont explicites (``BEGIN`` / ``COMMIT``), ce qu'exige l'invariant « une transaction par
    fenêtre » du moteur de recherche.
    """
    conn = open_connection(path, create=create)
    try:
        yield conn
    finally:
        conn.close()
