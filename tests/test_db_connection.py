"""Connection-level PRAGMAs: page cache sizing and WAL checkpointing on close."""

from pathlib import Path

from glyphwell.db import connect, initialize, open_connection


def test_open_connection_raises_the_page_cache(tmp_path: Path) -> None:
    """The default SQLite cache (~2 MB) is negligible next to a multi-GB `titles` table."""
    path = tmp_path / "glyphwell.db"
    conn = open_connection(path, create=True)
    try:
        cache_size_kib = int(conn.execute("PRAGMA cache_size").fetchone()[0])
        assert cache_size_kib < 0  # negative: SQLite interprets it as KiB, not pages
        assert abs(cache_size_kib) >= 262_144
    finally:
        conn.close()


def test_connect_checkpoints_the_wal_on_close(tmp_path: Path) -> None:
    """The WAL must not be left to grow unboundedly across CLI invocations."""
    path = tmp_path / "glyphwell.db"
    with connect(path, create=True) as conn:
        initialize(conn)
        conn.execute("BEGIN")
        for value in range(500):
            conn.execute(
                "INSERT INTO imports (source, file_name, row_count) VALUES (?, ?, ?)",
                ("imdb_basics", f"file-{value}.tsv", value),
            )
        conn.execute("COMMIT")

    wal_path = path.with_name(path.name + "-wal")
    assert not wal_path.exists() or wal_path.stat().st_size == 0
