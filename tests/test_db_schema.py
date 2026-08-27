"""The two schemas apply cleanly and carry the right version."""

import sqlite3
from pathlib import Path

from glyphwell.db import (
    CATALOG_SCHEMA_VERSION,
    RUN_SCHEMA_VERSION,
    current_version,
    initialize_catalog,
    initialize_run,
)

CATALOG_TABLES = {"titles", "subtitle_files", "corpus_downloads", "imports"}
RUN_TABLES = {"runs", "run_files", "results"}


def test_initialize_catalog_sets_schema_version(catalog_db: sqlite3.Connection) -> None:
    assert current_version(catalog_db) == CATALOG_SCHEMA_VERSION


def test_initialize_run_sets_schema_version(run_db: sqlite3.Connection) -> None:
    assert current_version(run_db) == RUN_SCHEMA_VERSION


def test_initialize_catalog_creates_all_tables(catalog_db: sqlite3.Connection) -> None:
    rows = catalog_db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert {row["name"] for row in rows} >= CATALOG_TABLES


def test_initialize_run_creates_all_tables(run_db: sqlite3.Connection) -> None:
    rows = run_db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert {row["name"] for row in rows} >= RUN_TABLES


def test_initialize_catalog_is_idempotent(catalog_db: sqlite3.Connection) -> None:
    """`db init` must be rerunnable without error on a database already in place."""
    assert initialize_catalog(catalog_db) == CATALOG_SCHEMA_VERSION


def test_initialize_run_is_idempotent(run_db: sqlite3.Connection) -> None:
    """``search run`` calls `initialize_run` on every invocation — must be a no-op."""
    assert initialize_run(run_db) == RUN_SCHEMA_VERSION


def test_no_full_text_index(catalog_db: sqlite3.Connection, run_db: sqlite3.Connection) -> None:
    """Design choice: subtitle text is never indexed in either database."""
    for conn in (catalog_db, run_db):
        rows = conn.execute("SELECT name FROM sqlite_master").fetchall()
        assert not [row["name"] for row in rows if "fts" in row["name"].lower()]


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row["name"] for row in rows}


def test_fresh_catalog_has_no_secondary_titles_indexes(catalog_db: sqlite3.Connection) -> None:
    """The only lookup direction this project needs is imdb_id -> title (primary key):
    a secondary index on parent_imdb_id or (title_type, start_year) would only serve a
    reverse lookup nothing here performs, at a real cost to bulk-import throughput."""
    names = _index_names(catalog_db)
    assert "idx_titles_parent" not in names
    assert "idx_titles_type_year" not in names


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def test_fresh_catalog_has_no_per_file_checksum_or_bookkeeping_columns(
    catalog_db: sqlite3.Connection,
) -> None:
    """A changed subtitle arrives under a new opensubtitles_file_id rather than mutating
    an existing one (ADR-0015, supersedes ADR-0006): there is no column to compare, and
    `discovered_at`/`updated_at` were never read back by anything (see ADR-0018)."""
    columns = _column_names(catalog_db, "subtitle_files")
    assert "sha256" not in columns
    assert "discovered_at" not in columns
    assert "updated_at" not in columns


def test_fresh_catalog_titles_has_no_removed_columns(catalog_db: sqlite3.Connection) -> None:
    """`is_adult`/`runtime_minutes`/`source`/`imported_at` are dropped: none were ever
    consulted by the code (see ADR-0018)."""
    columns = _column_names(catalog_db, "titles")
    assert columns.isdisjoint({"is_adult", "runtime_minutes", "source", "imported_at"})


def test_fresh_catalog_ids_are_integers(catalog_db: sqlite3.Connection) -> None:
    """`imdb_id`/`opensubtitles_file_id` are stored as compact integers, `tt` stripped —
    see `glyphwell.corpus.layout.imdb_id_to_int`/`imdb_id_from_int`."""
    titles_columns = {
        row["name"]: row["type"] for row in catalog_db.execute("PRAGMA table_info(titles)")
    }
    files_columns = {
        row["name"]: row["type"] for row in catalog_db.execute("PRAGMA table_info(subtitle_files)")
    }
    assert titles_columns["imdb_id"] == "INTEGER"
    assert titles_columns["parent_imdb_id"] == "INTEGER"
    assert files_columns["imdb_id"] == "INTEGER"
    assert files_columns["opensubtitles_file_id"] == "INTEGER"


def test_fresh_run_files_has_no_per_file_checksum_column(run_db: sqlite3.Connection) -> None:
    assert "file_sha256" not in _column_names(run_db, "run_files")


def test_fresh_run_files_has_rel_path(run_db: sqlite3.Connection) -> None:
    """Duplicated from the catalog's `subtitle_files.rel_path` at enqueue time, so the
    work queue's deterministic order needs no cross-database join (see ADR-0018)."""
    assert "rel_path" in _column_names(run_db, "run_files")


def test_fresh_run_has_calibrated_response_ratio_column(run_db: sqlite3.Connection) -> None:
    """ADR-0022's locked calibration ratio — see `glyphwell.search.calibration`."""
    assert "calibrated_response_ratio" in _column_names(run_db, "runs")


def test_run_migration_from_v1_adds_calibrated_response_ratio_column(tmp_path: Path) -> None:
    """A pre-ADR-0022 run database (version 1, no calibration column) upgrades cleanly,
    and rows written before the upgrade are preserved."""
    path = tmp_path / "old_run.db"
    seed = sqlite3.connect(path, isolation_level=None)
    try:
        # The `runs` table exactly as version 1 shipped it, before ADR-0022's column.
        seed.executescript(
            """
            CREATE TABLE runs (
                run_id            INTEGER PRIMARY KEY,
                manifest_path     TEXT NOT NULL,
                manifest_hash     TEXT NOT NULL,
                manifest_snapshot TEXT NOT NULL,
                model             TEXT NOT NULL,
                status            TEXT NOT NULL DEFAULT 'pending',
                created_at        TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at       TEXT
            ) STRICT;
            """
        )
        seed.execute(
            "INSERT INTO runs (manifest_path, manifest_hash, manifest_snapshot, model)"
            " VALUES ('m.yaml', 'hash-a', 'name: m', 'test-model')"
        )
        seed.execute("PRAGMA user_version = 1")
    finally:
        seed.close()

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        assert initialize_run(conn) == RUN_SCHEMA_VERSION
        assert current_version(conn) == RUN_SCHEMA_VERSION
        row = conn.execute("SELECT * FROM runs WHERE manifest_hash = 'hash-a'").fetchone()
        assert row["manifest_path"] == "m.yaml"
        assert row["calibrated_response_ratio"] is None
    finally:
        conn.close()


def test_results_unique_constraint_enforces_idempotence(run_db: sqlite3.Connection) -> None:
    """Core guarantee of resuming: a chunk can never be recorded twice.

    `run_files`/`results.file_id` are soft references (see ADR-0018): no `subtitle_files`
    row is needed in this database to exercise the constraint.
    """
    run_db.execute(
        "INSERT INTO runs (manifest_path, manifest_hash, manifest_snapshot, model)"
        " VALUES ('m.yaml', 'deadbeef', 'name: m', 'test-model')"
    )
    insert = (
        "INSERT INTO results"
        " (run_id, file_id, chunk_index, first_sentence_index, last_sentence_index, model)"
        " VALUES (1, 1, 0, 0, 79, 'test-model')"
    )
    run_db.execute(insert)

    # Replaying a chunk after an interruption must not create a duplicate.
    run_db.execute(insert.replace("INSERT INTO", "INSERT OR IGNORE INTO"))

    count = run_db.execute("SELECT count(*) AS n FROM results").fetchone()["n"]
    assert count == 1
