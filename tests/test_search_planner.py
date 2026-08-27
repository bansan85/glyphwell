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


def _seed_duplicate_files(
    conn: sqlite3.Connection, *, imdb_id: str, sizes: list[int], start: int = 0
) -> None:
    """Seeds one title with several competing subtitle files, of the given sizes."""
    titles = TitlesRepository(conn)
    files = SubtitleFilesRepository(conn)
    titles.upsert_many(
        [
            TitleRow(
                imdb_id=imdb_id,
                title_type="movie",
                primary_title=f"Title {imdb_id}",
                original_title=None,
                start_year=2000,
                end_year=None,
                parent_imdb_id=None,
                season_number=None,
                episode_number=None,
            )
        ]
    )
    for offset, size in enumerate(sizes):
        i = start + offset
        files.upsert(
            SubtitleFileRow(
                file_id=0,
                opus_version="v2024",
                language="en",
                imdb_id=imdb_id,
                opensubtitles_file_id=str(i),
                rel_path=f"OpenSubtitles/raw/en/2000/{imdb_id[2:]}/{i}.xml",
                year=2000,
                size_bytes=size,
                sentence_count=None,
            )
        )


def test_enqueue_paginates_across_batch_boundaries(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queue spanning several pages must be enqueued in full, not just the first page."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 3)
    _seed_files(catalog_db, 7)
    run_id = _create_run(run_db)

    added = planner.enqueue(catalog_db, run_db, run_id=run_id, select=SelectConfig())

    assert added == 7
    _done, planned = planner.plan_size(run_db, run_id)
    assert planned == 7


def test_enqueue_is_idempotent(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-running enqueue (to catch up new corpus files) must not duplicate existing rows."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 3)
    _seed_files(catalog_db, 7)
    run_id = _create_run(run_db)
    planner.enqueue(catalog_db, run_db, run_id=run_id, select=SelectConfig())

    added_again = planner.enqueue(catalog_db, run_db, run_id=run_id, select=SelectConfig())

    assert added_again == 0
    _done, planned = planner.plan_size(run_db, run_id)
    assert planned == 7


def test_enqueue_respects_title_type_filter_across_pages(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The select filter must still apply correctly once the query is paginated."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 2)
    _seed_files(catalog_db, 3, start=0, title_type="movie")
    _seed_files(catalog_db, 3, start=3, title_type="tvSeries")
    run_id = _create_run(run_db)

    added = planner.enqueue(
        catalog_db, run_db, run_id=run_id, select=SelectConfig(title_types=("movie",))
    )

    assert added == 3


def test_enqueue_expands_a_series_id_to_its_episodes(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection
) -> None:
    """`select.imdb_ids` naming a series must enqueue every episode linked to it."""
    titles = TitlesRepository(catalog_db)
    files = SubtitleFilesRepository(catalog_db)
    titles.upsert_many(
        [
            TitleRow(
                imdb_id="tt0047763",
                title_type="tvSeries",
                primary_title="A Series",
                original_title=None,
                start_year=1956,
                end_year=None,
                parent_imdb_id=None,
                season_number=None,
                episode_number=None,
            ),
            TitleRow(
                imdb_id="tt0674159",
                title_type="tvEpisode",
                primary_title="An Episode",
                original_title=None,
                start_year=1956,
                end_year=None,
                parent_imdb_id="tt0047763",
                season_number=2,
                episode_number=13,
            ),
            TitleRow(
                imdb_id="tt0133093",
                title_type="movie",
                primary_title="An Unrelated Movie",
                original_title=None,
                start_year=1999,
                end_year=None,
                parent_imdb_id=None,
                season_number=None,
                episode_number=None,
            ),
        ]
    )
    files.upsert(
        SubtitleFileRow(
            file_id=0,
            opus_version="v2024",
            language="en",
            imdb_id="tt0674159",
            opensubtitles_file_id="1957044904",
            rel_path="OpenSubtitles/raw/en/1956/674159_47763_2_13/1957044904.xml",
            year=1956,
            size_bytes=None,
            sentence_count=None,
        )
    )
    files.upsert(
        SubtitleFileRow(
            file_id=0,
            opus_version="v2024",
            language="en",
            imdb_id="tt0133093",
            opensubtitles_file_id="1",
            rel_path="OpenSubtitles/raw/en/1999/0133093/1.xml",
            year=1999,
            size_bytes=None,
            sentence_count=None,
        )
    )
    run_id = _create_run(run_db)

    added = planner.enqueue(
        catalog_db, run_db, run_id=run_id, select=SelectConfig(imdb_ids=(47763,))
    )

    assert added == 1
    planned = list(planner.iter_work(run_db, run_id=run_id))
    assert [file.rel_path for file in planned] == [
        "OpenSubtitles/raw/en/1956/674159_47763_2_13/1957044904.xml"
    ]


def test_enqueue_keeps_one_file_per_title_by_default(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection
) -> None:
    """`select.one_subtitle_per_title` defaults to true: OpenSubtitles carries several
    translations per title, and only the winning one should reach the queue."""
    _seed_duplicate_files(catalog_db, imdb_id="tt0133093", sizes=[80948, 80948, 98550])
    run_id = _create_run(run_db)

    added = planner.enqueue(catalog_db, run_db, run_id=run_id, select=SelectConfig())

    assert added == 1
    planned = list(planner.iter_work(run_db, run_id=run_id))
    assert [file.rel_path for file in planned] == ["OpenSubtitles/raw/en/2000/0133093/2.xml"]


def test_enqueue_can_disable_deduplication(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection
) -> None:
    _seed_duplicate_files(catalog_db, imdb_id="tt0133093", sizes=[80948, 80948, 98550])
    run_id = _create_run(run_db)

    added = planner.enqueue(
        catalog_db, run_db, run_id=run_id, select=SelectConfig(one_subtitle_per_title=False)
    )

    assert added == 3


def test_enqueue_deduplication_holds_across_batch_boundaries(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The dedup pre-pass and the paginated write loop must agree on every page, not just
    the first — each of several titles keeps exactly one winner."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 2)
    for n in range(5):
        _seed_duplicate_files(catalog_db, imdb_id=f"tt{n:07d}", sizes=[1000, 5000], start=n * 10)
    run_id = _create_run(run_db)

    added = planner.enqueue(catalog_db, run_db, run_id=run_id, select=SelectConfig())

    assert added == 5
    planned = list(planner.iter_work(run_db, run_id=run_id))
    assert all(file.rel_path.endswith(f"{n * 10 + 1}.xml") for n, file in enumerate(planned))


def test_iter_work_reflects_enqueued_rel_path_order(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection
) -> None:
    """`iter_work` reads `run_files` alone — no join back to the catalog database."""
    _seed_files(catalog_db, 3)
    run_id = _create_run(run_db)
    planner.enqueue(catalog_db, run_db, run_id=run_id, select=SelectConfig())

    planned = list(planner.iter_work(run_db, run_id=run_id))

    assert [file.rel_path for file in planned] == sorted(file.rel_path for file in planned)
    assert len(planned) == 3


def test_enqueue_reports_progress_once_per_scanned_row(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection
) -> None:
    """With deduplication active, `on_progress` fires once per row of the dedup pre-pass
    scan — the dominant cost `enqueue`'s docstring describes — and again once per row of
    the paginated write loop, which (restricted to `dedup_winners`) rescans the same 5
    rows here since none of these titles has a competing translation."""
    _seed_files(catalog_db, 5)
    run_id = _create_run(run_db)
    calls = 0

    def on_progress() -> None:
        nonlocal calls
        calls += 1

    planner.enqueue(
        catalog_db, run_db, run_id=run_id, select=SelectConfig(), on_progress=on_progress
    )

    assert calls == 10


def test_enqueue_reports_progress_without_deduplication(
    catalog_db: sqlite3.Connection, run_db: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With deduplication disabled, `on_progress` still fires once per row — this time
    from `enqueue`'s own paginated query, across several pages."""
    monkeypatch.setattr(planner, "_ENQUEUE_BATCH_SIZE", 2)
    _seed_files(catalog_db, 5)
    run_id = _create_run(run_db)
    calls = 0

    def on_progress() -> None:
        nonlocal calls
        calls += 1

    planner.enqueue(
        catalog_db,
        run_db,
        run_id=run_id,
        select=SelectConfig(one_subtitle_per_title=False),
        on_progress=on_progress,
    )

    assert calls == 5
