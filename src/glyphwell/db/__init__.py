"""SQLite persistence: connection, versioned schema, and typed access to tables."""

from glyphwell.db.connection import connect, open_connection
from glyphwell.db.migrations import (
    SCHEMA_VERSION,
    current_version,
    ensure_current,
    initialize,
    schema_sql,
)

__all__ = [
    "SCHEMA_VERSION",
    "connect",
    "current_version",
    "ensure_current",
    "initialize",
    "open_connection",
    "schema_sql",
]
