"""The schema applies cleanly and carries the right version."""

import sqlite3

from glyphwell.db import SCHEMA_VERSION, current_version, initialize

EXPECTED_TABLES = {
    "titles",
    "subtitle_files",
    "runs",
    "run_files",
    "results",
    "corpus_downloads",
    "imports",
}


def test_initialize_sets_schema_version(db: sqlite3.Connection) -> None:
    assert current_version(db) == SCHEMA_VERSION


def test_initialize_creates_all_tables(db: sqlite3.Connection) -> None:
    rows = db.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    assert {row["name"] for row in rows} >= EXPECTED_TABLES


def test_initialize_is_idempotent(db: sqlite3.Connection) -> None:
    """`db init` must be rerunnable without error on a database already in place."""
    assert initialize(db) == SCHEMA_VERSION


def test_no_full_text_index(db: sqlite3.Connection) -> None:
    """Design choice: subtitle text is never indexed in the database."""
    rows = db.execute("SELECT name FROM sqlite_master").fetchall()
    assert not [row["name"] for row in rows if "fts" in row["name"].lower()]


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'").fetchall()
    return {row["name"] for row in rows}


def test_fresh_database_has_no_secondary_titles_indexes(db: sqlite3.Connection) -> None:
    """The only lookup direction this project needs is imdb_id -> title (primary key):
    a secondary index on parent_imdb_id or (title_type, start_year) would only serve a
    reverse lookup nothing here performs, at a real cost to bulk-import throughput."""
    names = _index_names(db)
    assert "idx_titles_parent" not in names
    assert "idx_titles_type_year" not in names


def test_migration_from_v1_drops_secondary_titles_indexes() -> None:
    """A database created before schema.sql dropped these indexes must end up without
    them too, after `db init` runs the version-2 migration."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE titles (imdb_id TEXT PRIMARY KEY, parent_imdb_id TEXT,"
        " title_type TEXT, start_year INTEGER) STRICT"
    )
    conn.execute(
        "CREATE INDEX idx_titles_parent ON titles (parent_imdb_id) WHERE parent_imdb_id IS NOT NULL"
    )
    conn.execute("CREATE INDEX idx_titles_type_year ON titles (title_type, start_year)")
    conn.execute("PRAGMA user_version = 1")

    reached = initialize(conn)

    assert reached == SCHEMA_VERSION
    assert current_version(conn) == SCHEMA_VERSION
    names = _index_names(conn)
    assert "idx_titles_parent" not in names
    assert "idx_titles_type_year" not in names
    conn.close()


def test_results_unique_constraint_enforces_idempotence(db: sqlite3.Connection) -> None:
    """Core guarantee of resuming: a chunk can never be recorded twice."""
    db.execute(
        "INSERT INTO subtitle_files"
        " (opus_version, language, imdb_id, opensubtitles_file_id, rel_path)"
        " VALUES ('v2018', 'en', 'tt0133093', '3660124',"
        " 'OpenSubtitles/raw/en/1999/0133093/3660124.xml')"
    )
    db.execute(
        "INSERT INTO runs (manifest_path, manifest_hash, manifest_snapshot, model)"
        " VALUES ('m.yaml', 'deadbeef', 'name: m', 'test-model')"
    )
    insert = (
        "INSERT INTO results"
        " (run_id, file_id, chunk_index, first_sentence_index, last_sentence_index, model)"
        " VALUES (1, 1, 0, 0, 79, 'test-model')"
    )
    db.execute(insert)

    # Replaying a chunk after an interruption must not create a duplicate.
    db.execute(insert.replace("INSERT INTO", "INSERT OR IGNORE INTO"))

    count = db.execute("SELECT count(*) AS n FROM results").fetchone()["n"]
    assert count == 1
