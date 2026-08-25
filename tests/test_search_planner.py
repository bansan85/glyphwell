"""Work-queue construction: pagination, transaction batching, select filters."""

import sqlite3

import pytest

from glyphwell.db.repositories import (
    RunsRepository,
    SubtitleFileRow,
    SubtitleFilesRepository,
    TitleRow,
    TitlesRepository,
)
from glyphwell.manifest.model import SelectConfig
from glyphwell.search import planner


def _seed_files(
    conn: sqlite3.Connection, count: int, *, start: int = 0, title_type: str = "movie"
) -> None:
    """Seeds `count` distinct titles, each with one subtitle file, starting at `tt{start:07d}`.

    Distinct `start` values let a test seed two disjoint batches without colliding on
    `imdb_id` (the `titles` primary key) or on `subtitle_files`'
    `(opus_version, language, rel_path)` natural key.
    """
    titles = TitlesRepository(conn)
    files = SubtitleFilesRepository(conn)
    for i in range(start, start + count):
        imdb_id = f"tt{i:07d}"
        titles.upsert_many(
            [
                TitleRow(
                    imdb_id=imdb_id,
                    title_type=title_type,
                    primary_title=f"Title {i}",
                    original_title=None,
                    start_year=2000,
                    end_year=None,
                    is_adult=False,
                    runtime_minutes=None,
                    parent_imdb_id=None,
                    season_number=None,
                    episode_number=None,
                )
            ]
        )
        files.upsert(
            SubtitleFileRow(
                file_id=0,
                opus_version="v2024",
                language="en",
                imdb_id=imdb_id,
                opensubtitles_file_id=str(i),
                rel_path=f"OpenSubtitles/raw/en/2000/{imdb_id[2:]}/{i}.xml",
                year=2000,
                size_bytes=None,
                sentence_count=None,
            )
        )


def _create_run(conn: sqlite3.Connection) -> int:
    return RunsRepository(conn).create(
        manifest_path="m.yaml",
        manifest_hash="0" * 64,
        manifest_snapshot="name: t\n",
        model="test",
    )


def test_enqueue_paginates_across_batch_boundaries(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queue spanning several pages must be enqueued in full, not just the first page."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 3)
    _seed_files(db, 7)
    run_id = _create_run(db)

    added = planner.enqueue(db, run_id=run_id, select=SelectConfig())

    assert added == 7
    _done, planned = planner.plan_size(db, run_id)
    assert planned == 7


def test_enqueue_is_idempotent(db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-running enqueue (to catch up new corpus files) must not duplicate existing rows."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 3)
    _seed_files(db, 7)
    run_id = _create_run(db)
    planner.enqueue(db, run_id=run_id, select=SelectConfig())

    added_again = planner.enqueue(db, run_id=run_id, select=SelectConfig())

    assert added_again == 0
    _done, planned = planner.plan_size(db, run_id)
    assert planned == 7


def test_enqueue_respects_title_type_filter_across_pages(
    db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The select filter must still apply correctly once the query is paginated."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 2)
    _seed_files(db, 3, start=0, title_type="movie")
    _seed_files(db, 3, start=3, title_type="tvSeries")
    run_id = _create_run(db)

    added = planner.enqueue(db, run_id=run_id, select=SelectConfig(title_types=("movie",)))

    assert added == 3
