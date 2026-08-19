"""Création et versionnement du schéma.

La version vit dans ``PRAGMA user_version``, ce qui évite une table de migration
supplémentaire. Le schéma initial est déclaré une fois pour toutes dans ``schema.sql`` ;
les évolutions ultérieures s'ajoutent à `_MIGRATIONS` sous forme d'étapes numérotées.
"""

import sqlite3
from collections.abc import Mapping, Sequence
from importlib import resources
from typing import Final

from glyphwell.errors import DatabaseError, SchemaVersionError
from glyphwell.logging import get_logger

__all__ = ["SCHEMA_VERSION", "current_version", "ensure_current", "initialize", "schema_sql"]

_log = get_logger(__name__)

SCHEMA_VERSION: Final = 1
"""Version de schéma attendue par ce code."""

# Étapes de migration à appliquer pour passer de la version N-1 à la version N.
# La version 1 est produite par `schema.sql` et n'apparaît donc pas ici.
_MIGRATIONS: Final[Mapping[int, Sequence[str]]] = {}


def schema_sql() -> str:
    """Renvoie le contenu de ``schema.sql``, embarqué dans le paquet."""
    return resources.files("glyphwell.db").joinpath("schema.sql").read_text(encoding="utf-8")


def current_version(conn: sqlite3.Connection) -> int:
    """Version de schéma portée par la base. 0 pour une base vierge."""
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    version = row[0]
    if not isinstance(version, int):
        message = f"user_version inattendu : {version!r}"
        raise DatabaseError(message)
    return version


def initialize(conn: sqlite3.Connection) -> int:
    """Crée ou met à niveau le schéma, puis renvoie la version atteinte.

    Sans effet si la base est déjà à jour : ``schema.sql`` n'utilise que des
    ``CREATE ... IF NOT EXISTS``, et les migrations sont appliquées une seule fois.

    Raises:
        DatabaseError: la base est plus récente que ce que ce code sait lire.
    """
    version = current_version(conn)

    if version > SCHEMA_VERSION:
        message = (
            f"la base est en version {version}, ce code n'en gère que {SCHEMA_VERSION}. "
            "Mettre glyphwell à jour."
        )
        raise DatabaseError(message)

    if version == 0:
        _log.info("création du schéma (version %d)", SCHEMA_VERSION)
        conn.executescript(schema_sql())
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return SCHEMA_VERSION

    for target in range(version + 1, SCHEMA_VERSION + 1):
        statements = _MIGRATIONS.get(target)
        if statements is None:
            message = f"migration manquante vers la version {target}"
            raise DatabaseError(message)
        _log.info("migration %d -> %d", target - 1, target)
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {target}")
        conn.execute("COMMIT")

    return SCHEMA_VERSION


def ensure_current(conn: sqlite3.Connection) -> None:
    """Vérifie que la base est exactement à `SCHEMA_VERSION`, sans rien modifier.

    À appeler au début des commandes qui supposent un schéma en place, pour échouer avec un
    message utile plutôt que sur une table absente.

    Raises:
        SchemaVersionError: version différente de celle attendue.
    """
    version = current_version(conn)
    if version != SCHEMA_VERSION:
        message = (
            f"version de schéma {version}, attendu {SCHEMA_VERSION}. "
            "Lancer `glyphwell db init` pour créer ou mettre à niveau la base."
        )
        raise SchemaVersionError(message)
