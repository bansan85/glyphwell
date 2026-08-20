"""Schema creation and versioning.

The version lives in ``PRAGMA user_version``, which avoids an extra migration table.
The initial schema is declared once and for all in ``schema.sql``; later changes are
added to `_MIGRATIONS` as numbered steps.
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
"""Schema version expected by this code."""

# Migration steps to apply to go from version N-1 to version N.
# Version 1 is produced by `schema.sql` and therefore does not appear here.
_MIGRATIONS: Final[Mapping[int, Sequence[str]]] = {}


def schema_sql() -> str:
    """Returns the contents of ``schema.sql``, bundled with the package."""
    return resources.files("glyphwell.db").joinpath("schema.sql").read_text(encoding="utf-8")


def current_version(conn: sqlite3.Connection) -> int:
    """Schema version carried by the database. 0 for a fresh database."""
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    version = row[0]
    if not isinstance(version, int):
        message = f"unexpected user_version: {version!r}"
        raise DatabaseError(message)
    return version


def initialize(conn: sqlite3.Connection) -> int:
    """Creates or upgrades the schema, then returns the version reached.

    No-op if the database is already up to date: ``schema.sql`` only uses
    ``CREATE ... IF NOT EXISTS``, and migrations are applied only once.

    Raises:
        DatabaseError: the database is newer than what this code knows how to read.
    """
    version = current_version(conn)

    if version > SCHEMA_VERSION:
        message = (
            f"the database is at version {version}, this code only handles {SCHEMA_VERSION}. "
            "Update glyphwell."
        )
        raise DatabaseError(message)

    if version == 0:
        _log.info("creating schema (version %d)", SCHEMA_VERSION)
        conn.executescript(schema_sql())
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return SCHEMA_VERSION

    for target in range(version + 1, SCHEMA_VERSION + 1):
        statements = _MIGRATIONS.get(target)
        if statements is None:
            message = f"missing migration to version {target}"
            raise DatabaseError(message)
        _log.info("migration %d -> %d", target - 1, target)
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {target}")
        conn.execute("COMMIT")

    return SCHEMA_VERSION


def ensure_current(conn: sqlite3.Connection) -> None:
    """Checks that the database is exactly at `SCHEMA_VERSION`, without modifying anything.

    Call this at the start of commands that assume a schema is in place, to fail with a
    useful message rather than on a missing table.

    Raises:
        SchemaVersionError: version differs from the one expected.
    """
    version = current_version(conn)
    if version != SCHEMA_VERSION:
        message = (
            f"schema version {version}, expected {SCHEMA_VERSION}. "
            "Run `glyphwell db init` to create or upgrade the database."
        )
        raise SchemaVersionError(message)
