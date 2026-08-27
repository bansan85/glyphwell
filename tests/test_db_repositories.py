"""Traceability of corpus acquisitions, titles, and IMDb dataset imports."""

import sqlite3

import pytest

from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
    EpisodeLink,
    FileStatus,
    ImportRow,
    ImportSource,
    ImportsRepository,
    ResultRow,
    ResultsRepository,
    RunFilesRepository,
    RunsRepository,
    RunStatus,
    SubtitleFileRow,
    SubtitleFilesRepository,
    TitleRow,
    TitlesRepository,
)
from glyphwell.types import JsonObject


def _row(**overrides: str | None) -> CorpusDownloadRow:
    fields: dict[str, str | None] = {
        "opus_corpus": "OpenSubtitles",
        "opus_version": "v2018",
        "language": "en",
        "url": "https://example.invalid/en.zip",
        "archive_path": None,
        "sha256": None,
    }
    fields.update(overrides)
    return CorpusDownloadRow(
        opus_corpus=str(fields["opus_corpus"]),
        opus_version=str(fields["opus_version"]),
        language=str(fields["language"]),
        url=fields["url"],
        archive_path=fields["archive_path"],
        sha256=fields["sha256"],
        status=DownloadStatus.PENDING,
    )


def test_upsert_then_get(catalog_db: sqlite3.Connection) -> None:
    repo = CorpusDownloadsRepository(catalog_db)
    download_id = repo.upsert(_row())

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.download_id == download_id
    assert found.status is DownloadStatus.PENDING
    assert found.downloaded_at is None


def test_upsert_is_idempotent_on_the_natural_key(catalog_db: sqlite3.Connection) -> None:
    """Rerunning `corpus fetch` must reuse the same row, not stack a second one."""
    repo = CorpusDownloadsRepository(catalog_db)
    first = repo.upsert(_row())
    second = repo.upsert(_row())

    assert first == second
    assert len(list(repo.iter_all())) == 1


def test_mark_records_completion(catalog_db: sqlite3.Connection) -> None:
    repo = CorpusDownloadsRepository(catalog_db)
    download_id = repo.upsert(_row())

    repo.mark(
        download_id,
        DownloadStatus.DOWNLOADED,
        sha256="ab" * 32,
        archive_path="data/corpus/en.zip",
        verified=True,
    )

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.status is DownloadStatus.DOWNLOADED
    assert found.sha256 == "ab" * 32
    assert found.archive_path == "data/corpus/en.zip"
    assert found.downloaded_at is not None
    assert found.verified_at is not None


def test_a_known_hash_survives_a_later_upsert(catalog_db: sqlite3.Connection) -> None:
    """A checksum is not computed for free: overwriting it with `NULL` would lose it."""
    repo = CorpusDownloadsRepository(catalog_db)
    download_id = repo.upsert(_row())
    repo.mark(download_id, DownloadStatus.DOWNLOADED, sha256="cd" * 32)

    repo.upsert(_row())

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.sha256 == "cd" * 32
    assert found.status is DownloadStatus.PENDING


def test_failure_is_recorded(catalog_db: sqlite3.Connection) -> None:
    repo = CorpusDownloadsRepository(catalog_db)
    download_id = repo.upsert(_row())

    repo.mark(download_id, DownloadStatus.FAILED)

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.status is DownloadStatus.FAILED
    assert found.downloaded_at is None


def test_versions_are_distinct_acquisitions(catalog_db: sqlite3.Connection) -> None:
    """Two releases of the same corpus coexist: the version is part of the key."""
    repo = CorpusDownloadsRepository(catalog_db)
    repo.upsert(_row())
    repo.upsert(_row(opus_version="v2024"))

    assert len(list(repo.iter_all())) == 2


def _movie(
    *,
    imdb_id: str = "tt0133093",
    title_type: str | None = "movie",
    primary_title: str | None = "The Matrix",
    parent_imdb_id: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> TitleRow:
    return TitleRow(
        imdb_id=imdb_id,
        title_type=title_type,
        primary_title=primary_title,
        original_title=primary_title,
        start_year=1999,
        end_year=None,
        parent_imdb_id=parent_imdb_id,
        season_number=season_number,
        episode_number=episode_number,
    )


def test_titles_upsert_then_get(catalog_db: sqlite3.Connection) -> None:
    repo = TitlesRepository(catalog_db)
    repo.upsert_many([_movie()])

    found = repo.get("tt0133093")
    assert found is not None
    assert found.primary_title == "The Matrix"
    assert repo.count() == 1


def test_titles_get_of_unknown_id_is_none(catalog_db: sqlite3.Connection) -> None:
    assert TitlesRepository(catalog_db).get("tt9999999") is None


def test_titles_upsert_does_not_clobber_the_episode_link(catalog_db: sqlite3.Connection) -> None:
    """A later `import_basics` re-run must not erase what `import_episodes` wrote.

    `import_basics` never knows the parent/season/episode columns: it always sends
    `None` for them. If `upsert_many` overwrote unconditionally instead of coalescing,
    re-running `fetch-imdb` + `import-imdb` would silently unlink every episode.
    """
    repo = TitlesRepository(catalog_db)
    repo.upsert_many([_movie(imdb_id="tt0041038", title_type="tvSeries")])
    repo.set_episode_links_many(
        [
            EpisodeLink(
                imdb_id="tt0041038",
                parent_imdb_id="tt0041037",
                season_number=1,
                episode_number=9,
            )
        ]
    )

    repo.upsert_many([_movie(imdb_id="tt0041038", title_type="tvSeries", primary_title="Renamed")])

    found = repo.get("tt0041038")
    assert found is not None
    assert found.primary_title == "Renamed"
    assert found.parent_imdb_id == "tt0041037"
    assert found.season_number == 1
    assert found.episode_number == 9


def test_set_episode_links_many_requires_an_existing_title(catalog_db: sqlite3.Connection) -> None:
    """An episode's own row must already exist — `import_episodes` only updates."""
    written = TitlesRepository(catalog_db).set_episode_links_many(
        [
            EpisodeLink(
                imdb_id="tt9999999",
                parent_imdb_id="tt0000001",
                season_number=1,
                episode_number=1,
            )
        ]
    )
    assert written == 0


def test_set_episode_links_many_leaves_other_columns_untouched(
    catalog_db: sqlite3.Connection,
) -> None:
    repo = TitlesRepository(catalog_db)
    repo.upsert_many([_movie(imdb_id="tt0041038", title_type="tvEpisode")])

    repo.set_episode_links_many(
        [
            EpisodeLink(
                imdb_id="tt0041038",
                parent_imdb_id="tt0041037",
                season_number=1,
                episode_number=9,
            )
        ]
    )

    found = repo.get("tt0041038")
    assert found is not None
    assert found.title_type == "tvEpisode"
    assert found.primary_title == "The Matrix"


def test_imports_record_then_iter_all(catalog_db: sqlite3.Connection) -> None:
    repo = ImportsRepository(catalog_db)
    repo.record(
        ImportRow(source=ImportSource.BASICS, file_name="title.basics.tsv.gz", row_count=42)
    )
    repo.record(
        ImportRow(source=ImportSource.EPISODE, file_name="title.episode.tsv.gz", row_count=7)
    )

    entries = list(repo.iter_all())
    assert [entry.source for entry in entries] == [ImportSource.EPISODE, ImportSource.BASICS]
    assert entries[1].row_count == 42
    assert entries[1].import_id is not None


def _file_row(
    *,
    opensubtitles_file_id: str = "3660124",
    rel_path: str = "OpenSubtitles/raw/en/1999/0133093/3660124.xml",
) -> SubtitleFileRow:
    return SubtitleFileRow(
        file_id=0,
        opus_version="v2024",
        language="en",
        imdb_id="tt0133093",
        opensubtitles_file_id=opensubtitles_file_id,
        rel_path=rel_path,
        year=1999,
        size_bytes=None,
        sentence_count=None,
    )


def test_subtitle_files_upsert_then_get_by_path(catalog_db: sqlite3.Connection) -> None:
    repo = SubtitleFilesRepository(catalog_db)
    file_id = repo.upsert(_file_row())

    found = repo.get_by_path(
        opus_version="v2024",
        language="en",
        rel_path="OpenSubtitles/raw/en/1999/0133093/3660124.xml",
    )
    assert found is not None
    assert found.file_id == file_id
    assert found.imdb_id == "tt0133093"
    assert repo.get(file_id) == found
    assert repo.count() == 1


def _run_id(conn: sqlite3.Connection, *, manifest_hash: str = "hash-a") -> int:
    return RunsRepository(conn).create(
        manifest_path="search.yaml",
        manifest_hash=manifest_hash,
        manifest_snapshot="name: a\nmodel: m\nprompt:\n  user: x\n",
        model="test-model",
    )


def test_runs_create_then_get(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    found = RunsRepository(run_db).get(run_id)
    assert found is not None
    assert found.status is RunStatus.PENDING
    assert found.manifest_hash == "hash-a"


def test_runs_get_manifest_snapshot(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    snapshot = RunsRepository(run_db).get_manifest_snapshot(run_id)
    assert snapshot == "name: a\nmodel: m\nprompt:\n  user: x\n"
    assert RunsRepository(run_db).get_manifest_snapshot(run_id + 999) is None


def test_runs_calibrated_response_ratio_defaults_to_none(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    assert RunsRepository(run_db).get_calibrated_response_ratio(run_id) is None


def test_runs_set_then_get_calibrated_response_ratio(run_db: sqlite3.Connection) -> None:
    """ADR-0022: the locked ratio is a dedicated column, written once by calibration."""
    run_id = _run_id(run_db)
    repo = RunsRepository(run_db)

    repo.set_calibrated_response_ratio(run_id, 0.42)

    assert repo.get_calibrated_response_ratio(run_id) == pytest.approx(0.42)


def test_runs_find_by_hash_most_recent_first(run_db: sqlite3.Connection) -> None:
    repo = RunsRepository(run_db)
    first = _run_id(run_db)
    second = _run_id(run_db)
    found = repo.find_by_hash("hash-a")
    assert [row.run_id for row in found] == [second, first]


def test_runs_set_status_sets_and_clears_finished_at(run_db: sqlite3.Connection) -> None:
    repo = RunsRepository(run_db)
    run_id = _run_id(run_db)

    repo.set_status(run_id, RunStatus.DONE)
    done = run_db.execute("SELECT finished_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert done["finished_at"] is not None
    after_done = repo.get(run_id)
    assert after_done is not None
    assert after_done.status is RunStatus.DONE

    repo.set_status(run_id, RunStatus.RUNNING)
    running = run_db.execute("SELECT finished_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert running["finished_at"] is None


def test_runs_list_all_most_recent_first(run_db: sqlite3.Connection) -> None:
    repo = RunsRepository(run_db)
    first = _run_id(run_db, manifest_hash="hash-a")
    second = _run_id(run_db, manifest_hash="hash-b")
    assert [row.run_id for row in repo.list_all()] == [second, first]


def test_runs_unfinished_excludes_done(run_db: sqlite3.Connection) -> None:
    repo = RunsRepository(run_db)
    done_run = _run_id(run_db, manifest_hash="hash-a")
    pending_run = _run_id(run_db, manifest_hash="hash-b")
    repo.set_status(done_run, RunStatus.DONE)

    assert [row.run_id for row in repo.unfinished()] == [pending_run]


def test_run_files_enqueue_many_counts_only_new_rows(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    repo = RunFilesRepository(run_db)

    assert repo.enqueue_many(run_id, [(1, "a/1.xml")]) == 1
    assert repo.enqueue_many(run_id, [(1, "a/1.xml"), (2, "a/2.xml")]) == 1


def test_run_files_iter_pending_excludes_terminal_statuses_and_orders_by_rel_path(
    run_db: sqlite3.Connection,
) -> None:
    run_id = _run_id(run_db)
    repo = RunFilesRepository(run_db)
    repo.enqueue_many(run_id, [(2, "b/2.xml"), (1, "a/1.xml"), (3, "c/3.xml")])
    repo.mark_done(run_id, 3)

    pending = list(repo.iter_pending(run_id))
    assert [row.file_id for row in pending] == [1, 2]
    assert [row.rel_path for row in pending] == ["a/1.xml", "b/2.xml"]


def test_run_files_mark_started_sets_started_at_once(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    file_id = 1
    repo = RunFilesRepository(run_db)
    repo.enqueue_many(run_id, [(file_id, "a/1.xml")])

    repo.mark_started(run_id, file_id)
    first = run_db.execute(
        "SELECT started_at FROM run_files WHERE run_id = ? AND file_id = ?", (run_id, file_id)
    ).fetchone()["started_at"]
    assert first is not None

    repo.mark_started(run_id, file_id)
    second = run_db.execute(
        "SELECT started_at FROM run_files WHERE run_id = ? AND file_id = ?", (run_id, file_id)
    ).fetchone()["started_at"]
    assert second == first


def test_run_files_mark_error_keeps_the_cursor(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    file_id = 1
    repo = RunFilesRepository(run_db)
    repo.enqueue_many(run_id, [(file_id, "a/1.xml")])
    repo.advance(run_id, file_id, last_sentence_index=9, last_sentence_id="s9", chunks_done=1)

    repo.mark_error(run_id, file_id, "boom")

    row = repo.get(run_id, file_id)
    assert row is not None
    assert row.status is FileStatus.ERROR
    assert row.error == "boom"
    assert row.last_sentence_index == 9
    assert row.chunks_done == 1


def test_run_files_advance_flips_pending_to_in_progress(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    file_id = 1
    repo = RunFilesRepository(run_db)
    repo.enqueue_many(run_id, [(file_id, "a/1.xml")])

    repo.advance(run_id, file_id, last_sentence_index=1, last_sentence_id="s1", chunks_done=1)

    row = repo.get(run_id, file_id)
    assert row is not None
    assert row.status is FileStatus.IN_PROGRESS
    assert row.last_sentence_index == 1
    assert row.last_sentence_id == "s1"


def test_run_files_progress_reports_every_status_with_zeros(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    RunFilesRepository(run_db).enqueue_many(run_id, [(1, "a/1.xml")])

    progress = RunFilesRepository(run_db).progress(run_id)

    assert progress == {
        FileStatus.PENDING: 1,
        FileStatus.IN_PROGRESS: 0,
        FileStatus.DONE: 0,
        FileStatus.SKIPPED: 0,
        FileStatus.ERROR: 0,
    }


def _result_row(
    *,
    run_id: int,
    file_id: int,
    chunk_index: int = 0,
    matched: bool = True,
    payload: JsonObject | None = None,
) -> ResultRow:
    return ResultRow(
        result_id=0,
        run_id=run_id,
        file_id=file_id,
        chunk_index=chunk_index,
        first_sentence_index=chunk_index,
        last_sentence_index=chunk_index,
        matched=matched,
        payload=payload,
        model="test-model",
        latency_ms=42,
    )


def test_results_insert_ignore_is_idempotent(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    file_id = 1
    RunFilesRepository(run_db).enqueue_many(run_id, [(file_id, "a/1.xml")])
    repo = ResultsRepository(run_db)
    row = _result_row(run_id=run_id, file_id=file_id)

    assert repo.insert_ignore(row) is True
    assert repo.insert_ignore(row) is False
    assert repo.count(run_id) == 1


def test_results_payload_round_trips_through_json(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    file_id = 1
    RunFilesRepository(run_db).enqueue_many(run_id, [(file_id, "a/1.xml")])
    repo = ResultsRepository(run_db)
    repo.insert_ignore(
        _result_row(run_id=run_id, file_id=file_id, payload={"matched": True, "n": 3})
    )

    matches = list(repo.iter_matches(run_id))
    assert len(matches) == 1
    assert matches[0].payload == {"matched": True, "n": 3}


def test_results_count_matched_only(run_db: sqlite3.Connection) -> None:
    run_id = _run_id(run_db)
    file_id = 1
    RunFilesRepository(run_db).enqueue_many(run_id, [(file_id, "a/1.xml")])
    repo = ResultsRepository(run_db)
    repo.insert_ignore(_result_row(run_id=run_id, file_id=file_id, chunk_index=0, matched=True))
    repo.insert_ignore(_result_row(run_id=run_id, file_id=file_id, chunk_index=1, matched=False))

    assert repo.count(run_id) == 2
    assert repo.count(run_id, matched_only=True) == 1
