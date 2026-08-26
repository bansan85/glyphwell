"""SQLite persistence: connection, versioned schemas, and typed access to tables."""

from glyphwell.db.connection import connect, open_connection
from glyphwell.db.migrations import (
    CATALOG_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    catalog_schema_sql,
    current_version,
    ensure_catalog_current,
    ensure_run_current,
    initialize_catalog,
    initialize_run,
    run_schema_sql,
)

__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION",
    "catalog_schema_sql",
    "connect",
    "current_version",
    "ensure_catalog_current",
    "ensure_run_current",
    "initialize_catalog",
    "initialize_run",
    "open_connection",
    "run_schema_sql",
]
