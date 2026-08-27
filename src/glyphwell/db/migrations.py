"""Schema creation and versioning.

The version lives in ``PRAGMA user_version``, which avoids an extra migration table.
Two independent schemas, hence two independent version histories: the catalog database
(``schema_catalog.sql``) and a search's run database (``schema_run.sql``) are separate
files and never share a `PRAGMA user_version`. Each initial schema is declared once and
for all in its ``.sql`` file; later changes to either are added to that schema's
migration mapping as numbered steps.
"""

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import resources
from typing import Final

from glyphwell.errors import DatabaseError, SchemaVersionError
from glyphwell.logging import get_logger

__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION",
    "catalog_schema_sql",
    "current_version",
    "ensure_catalog_current",
    "ensure_run_current",
    "initialize_catalog",
    "initialize_run",
    "run_schema_sql",
]

_log = get_logger(__name__)

CATALOG_SCHEMA_VERSION: Final = 1
"""Catalog schema version expected by this code."""

RUN_SCHEMA_VERSION: Final = 2
"""Run schema version expected by this code."""

# Migration steps to apply to go from version N-1 to version N. Version 1 is produced by
# the schema's own `.sql` file and therefore does not appear here. Both histories start
# fresh at 1: nothing has shipped with the old, single-database schema, so there is no
# prior version to carry forward (see ADR-0018).
_CATALOG_MIGRATIONS: Final[Mapping[int, Sequence[str]]] = {}
_RUN_MIGRATIONS: Final[Mapping[int, Sequence[str]]] = {
    # ADR-0022: locked response-to-input token ratio, NULL until a run's calibration
    # measures one. `schema_run.sql` already declares this column for a fresh database.
    2: ("ALTER TABLE runs ADD COLUMN calibrated_response_ratio REAL",),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class _SchemaSpec:
    """One schema's identity: its version, its migrations, and its `.sql` resource."""

    version: int
    migrations: Mapping[int, Sequence[str]]
    resource_name: str
    label: str


_CATALOG_SCHEMA = _SchemaSpec(
    version=CATALOG_SCHEMA_VERSION,
    migrations=_CATALOG_MIGRATIONS,
    resource_name="schema_catalog.sql",
    label="catalog",
)
_RUN_SCHEMA = _SchemaSpec(
    version=RUN_SCHEMA_VERSION,
    migrations=_RUN_MIGRATIONS,
    resource_name="schema_run.sql",
    label="run",
)


def _schema_sql(resource_name: str) -> str:
    """Returns the contents of a schema's `.sql` file, bundled with the package."""
    return resources.files("glyphwell.db").joinpath(resource_name).read_text(encoding="utf-8")


def catalog_schema_sql() -> str:
    """Returns the contents of ``schema_catalog.sql``."""
    return _schema_sql(_CATALOG_SCHEMA.resource_name)


def run_schema_sql() -> str:
    """Returns the contents of ``schema_run.sql``."""
    return _schema_sql(_RUN_SCHEMA.resource_name)


def current_version(conn: sqlite3.Connection) -> int:
    """Schema version carried by the database. 0 for a fresh database.

    Kind-agnostic: `PRAGMA user_version` means the same thing regardless of which of the
    two schemas the file holds.
    """
    row = conn.execute("PRAGMA user_version").fetchone()
    if row is None:
        return 0
    version = row[0]
    if not isinstance(version, int):
        message = f"unexpected user_version: {version!r}"
        raise DatabaseError(message)
    return version


def _initialize(conn: sqlite3.Connection, spec: _SchemaSpec) -> int:
    """Creates or upgrades a database against `spec`, then returns the version reached.

    No-op if the database is already up to date: the schema's `.sql` file only uses
    ``CREATE ... IF NOT EXISTS``, and migrations are applied only once.

    Raises:
        DatabaseError: the database is newer than what this code knows how to read.
    """
    version = current_version(conn)

    if version > spec.version:
        message = (
            f"the {spec.label} database is at version {version}, this code only handles "
            f"{spec.version}. Update glyphwell."
        )
        raise DatabaseError(message)

    if version == 0:
        _log.info("creating %s schema (version %d)", spec.label, spec.version)
        conn.executescript(_schema_sql(spec.resource_name))
        conn.execute(f"PRAGMA user_version = {spec.version}")
        return spec.version

    for target in range(version + 1, spec.version + 1):
        statements = spec.migrations.get(target)
        if statements is None:
            message = f"missing {spec.label} migration to version {target}"
            raise DatabaseError(message)
        _log.info("%s migration %d -> %d", spec.label, target - 1, target)
        conn.execute("BEGIN")
        for statement in statements:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {target}")
        conn.execute("COMMIT")

    return spec.version


def initialize_catalog(conn: sqlite3.Connection) -> int:
    """Creates or upgrades the catalog schema, then returns the version reached.

    Raises:
        DatabaseError: the database is newer than what this code knows how to read.
    """
    return _initialize(conn, _CATALOG_SCHEMA)


def initialize_run(conn: sqlite3.Connection) -> int:
    """Creates or upgrades a run schema, then returns the version reached.

    Idempotent: ``search run`` calls this on every invocation, since a run database has
    no separate init step.

    Raises:
        DatabaseError: the database is newer than what this code knows how to read.
    """
    return _initialize(conn, _RUN_SCHEMA)


def _ensure_current(conn: sqlite3.Connection, spec: _SchemaSpec) -> None:
    """Checks that the database is exactly at `spec.version`, without modifying anything.

    Raises:
        SchemaVersionError: version differs from the one expected.
    """
    version = current_version(conn)
    if version != spec.version:
        message = (
            f"{spec.label} schema version {version}, expected {spec.version}. "
            "Run `glyphwell db init` to create or upgrade the database."
        )
        raise SchemaVersionError(message)


def ensure_catalog_current(conn: sqlite3.Connection) -> None:
    """Checks that the catalog database is exactly at `CATALOG_SCHEMA_VERSION`.

    Call this at the start of commands that assume the catalog schema is in place, to
    fail with a useful message rather than on a missing table.

    Raises:
        SchemaVersionError: version differs from the one expected.
    """
    _ensure_current(conn, _CATALOG_SCHEMA)


def ensure_run_current(conn: sqlite3.Connection) -> None:
    """Checks that a run database is exactly at `RUN_SCHEMA_VERSION`.

    Raises:
        SchemaVersionError: version differs from the one expected.
    """
    _ensure_current(conn, _RUN_SCHEMA)
