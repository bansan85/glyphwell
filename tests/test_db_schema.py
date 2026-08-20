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
