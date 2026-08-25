"""Opening SQLite connections.

A single place configures the PRAGMAs: WAL mode is essential here, because the search
engine writes one result per chunk while another command (``db status``,
``search status``) may be reading the database.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from glyphwell.errors import DatabaseError
from glyphwell.logging import get_logger

__all__ = ["connect", "open_connection"]

_log = get_logger(__name__)

# 30 s: an IMDb dataset import holds the write lock for a while.
_BUSY_TIMEOUT_MS = 30_000

# 256 MiB: comfortably larger than a toy database, still modest next to `titles`
# (multi-GB), but enough to keep the working set of a corpus-wide join in memory.
_CACHE_SIZE_KIB = 262_144


def open_connection(path: Path, *, create: bool = False) -> sqlite3.Connection:
    """Opens the database and applies the project's PRAGMAs.

    Args:
        path: path to the SQLite file.
        create: if false, a missing file is an error — this avoids silently creating an
            empty database when the user got the path wrong.

    Raises:
        DatabaseError: the database is missing while `create` is false, or opening failed.
    """
    if not create and not path.exists():
        message = f"database not found: {path}. Run `glyphwell db init` first."
        raise DatabaseError(message)

    if create:
        path.parent.mkdir(parents=True, exist_ok=True)

    try:
        conn = sqlite3.connect(path, timeout=_BUSY_TIMEOUT_MS / 1000, isolation_level=None)
    except sqlite3.Error as exc:
        message = f"could not open {path}: {exc}"
        raise DatabaseError(message) from exc

    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA temp_store = MEMORY")
    # SQLite's own default (~2 MB) is negligible next to `titles`, which alone runs into
    # the gigabytes: too small a cache turns point lookups into disk round-trips.
    conn.execute(f"PRAGMA cache_size = -{_CACHE_SIZE_KIB}")
    _log.debug("database opened: %s", path)
    return conn


@contextmanager
def connect(path: Path, *, create: bool = False) -> Iterator[sqlite3.Connection]:
    """Context manager around `open_connection` that guarantees closing.

    `isolation_level=None` disables sqlite3's implicit autocommit: transactions are
    explicit (``BEGIN`` / ``COMMIT``), which the search engine's "one transaction per
    chunk" invariant requires.

    Checkpoints and truncates the WAL before closing: WAL mode otherwise lets it grow
    across invocations with nothing ever reclaiming it, since SQLite's own automatic
    checkpoint only runs opportunistically and can be held back for as long as a reader
    stays open.
    """
    conn = open_connection(path, create=create)
    try:
        yield conn
    finally:
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            _log.warning("could not checkpoint the WAL for %s", path)
        conn.close()
