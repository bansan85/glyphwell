"""Traceability of corpus acquisitions, titles, and IMDb dataset imports."""

import sqlite3

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


def test_upsert_then_get(db: sqlite3.Connection) -> None:
    repo = CorpusDownloadsRepository(db)
    download_id = repo.upsert(_row())

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.download_id == download_id
    assert found.status is DownloadStatus.PENDING
    assert found.downloaded_at is None


def test_upsert_is_idempotent_on_the_natural_key(db: sqlite3.Connection) -> None:
    """Rerunning `corpus fetch` must reuse the same row, not stack a second one."""
    repo = CorpusDownloadsRepository(db)
    first = repo.upsert(_row())
    second = repo.upsert(_row())

    assert first == second
    assert len(list(repo.iter_all())) == 1


def test_mark_records_completion(db: sqlite3.Connection) -> None:
    repo = CorpusDownloadsRepository(db)
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


def test_a_known_hash_survives_a_later_upsert(db: sqlite3.Connection) -> None:
    """A checksum is not computed for free: overwriting it with `NULL` would lose it."""
    repo = CorpusDownloadsRepository(db)
    download_id = repo.upsert(_row())
    repo.mark(download_id, DownloadStatus.DOWNLOADED, sha256="cd" * 32)

    repo.upsert(_row())

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.sha256 == "cd" * 32
    assert found.status is DownloadStatus.PENDING


def test_failure_is_recorded(db: sqlite3.Connection) -> None:
    repo = CorpusDownloadsRepository(db)
    download_id = repo.upsert(_row())

    repo.mark(download_id, DownloadStatus.FAILED)

    found = repo.get(opus_corpus="OpenSubtitles", opus_version="v2018", language="en")
    assert found is not None
    assert found.status is DownloadStatus.FAILED
    assert found.downloaded_at is None


def test_versions_are_distinct_acquisitions(db: sqlite3.Connection) -> None:
    """Two releases of the same corpus coexist: the version is part of the key."""
    repo = CorpusDownloadsRepository(db)
    repo.upsert(_row())
    repo.upsert(_row(opus_version="v2024"))

    assert len(list(repo.iter_all())) == 2


def _movie(
    *,
    imdb_id: str = "tt0133093",
    title_type: str | None = "movie",
    primary_title: str | None = "The Matrix",
    is_adult: bool = False,
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
        is_adult=is_adult,
        runtime_minutes=136,
        parent_imdb_id=parent_imdb_id,
        season_number=season_number,
        episode_number=episode_number,
    )


def test_titles_upsert_then_get(db: sqlite3.Connection) -> None:
    repo = TitlesRepository(db)
    repo.upsert_many([_movie()])

    found = repo.get("tt0133093")
    assert found is not None
    assert found.primary_title == "The Matrix"
    assert found.is_adult is False
    assert repo.count() == 1


def test_titles_get_of_unknown_id_is_none(db: sqlite3.Connection) -> None:
    assert TitlesRepository(db).get("tt9999999") is None


def test_titles_upsert_does_not_clobber_the_episode_link(db: sqlite3.Connection) -> None:
    """A later `import_basics` re-run must not erase what `import_episodes` wrote.

    `import_basics` never knows the parent/season/episode columns: it always sends
    `None` for them. If `upsert_many` overwrote unconditionally instead of coalescing,
    re-running `fetch-imdb` + `import-imdb` would silently unlink every episode.
    """
    repo = TitlesRepository(db)
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


def test_set_episode_links_many_requires_an_existing_title(db: sqlite3.Connection) -> None:
    """An episode's own row must already exist — `import_episodes` only updates."""
    written = TitlesRepository(db).set_episode_links_many(
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


def test_set_episode_links_many_leaves_other_columns_untouched(db: sqlite3.Connection) -> None:
    repo = TitlesRepository(db)
    repo.upsert_many([_movie(imdb_id="tt0041038", title_type="tvEpisode", is_adult=True)])

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
    assert found.is_adult is True
    assert found.title_type == "tvEpisode"


def test_imports_record_then_iter_all(db: sqlite3.Connection) -> None:
    repo = ImportsRepository(db)
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
        sha256=None,
        size_bytes=None,
        sentence_count=None,
    )


def test_subtitle_files_upsert_then_get_by_path(db: sqlite3.Connection) -> None:
    repo = SubtitleFilesRepository(db)
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


def test_subtitle_files_upsert_does_not_clobber_a_known_hash(db: sqlite3.Connection) -> None:
    """A re-catalog pass (no content read) must not blank out a checksum already set."""
    repo = SubtitleFilesRepository(db)
    file_id = repo.upsert(_file_row())
    repo.set_hash(file_id, "ab" * 32, size_bytes=1234)

    repo.upsert(_file_row())  # simulates a second `corpus index` pass, sha256=None again

    found = repo.get(file_id)
    assert found is not None
    assert found.sha256 == "ab" * 32
    assert found.size_bytes == 1234


def test_subtitle_files_iter_stale_only_returns_unhashed_rows(db: sqlite3.Connection) -> None:
    repo = SubtitleFilesRepository(db)
    hashed_id = repo.upsert(_file_row(opensubtitles_file_id="1", rel_path="a/1.xml"))
    repo.set_hash(hashed_id, "cd" * 32, size_bytes=1)
    stale_id = repo.upsert(_file_row(opensubtitles_file_id="2", rel_path="a/2.xml"))

    stale = list(repo.iter_stale())
    assert [row.file_id for row in stale] == [stale_id]


def _run_id(conn: sqlite3.Connection, *, manifest_hash: str = "hash-a") -> int:
    return RunsRepository(conn).create(
        manifest_path="search.yaml",
        manifest_hash=manifest_hash,
        manifest_snapshot="name: a\nmodel: m\nprompt:\n  user: x\n",
        model="test-model",
    )


def test_runs_create_then_get(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    found = RunsRepository(db).get(run_id)
    assert found is not None
    assert found.status is RunStatus.PENDING
    assert found.manifest_hash == "hash-a"


def test_runs_get_manifest_snapshot(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    snapshot = RunsRepository(db).get_manifest_snapshot(run_id)
    assert snapshot == "name: a\nmodel: m\nprompt:\n  user: x\n"
    assert RunsRepository(db).get_manifest_snapshot(run_id + 999) is None


def test_runs_find_by_hash_most_recent_first(db: sqlite3.Connection) -> None:
    repo = RunsRepository(db)
    first = _run_id(db)
    second = _run_id(db)
    found = repo.find_by_hash("hash-a")
    assert [row.run_id for row in found] == [second, first]


def test_runs_set_status_sets_and_clears_finished_at(db: sqlite3.Connection) -> None:
    repo = RunsRepository(db)
    run_id = _run_id(db)

    repo.set_status(run_id, RunStatus.DONE)
    done = db.execute("SELECT finished_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert done["finished_at"] is not None
    after_done = repo.get(run_id)
    assert after_done is not None
    assert after_done.status is RunStatus.DONE

    repo.set_status(run_id, RunStatus.RUNNING)
    running = db.execute("SELECT finished_at FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    assert running["finished_at"] is None


def test_runs_list_all_most_recent_first(db: sqlite3.Connection) -> None:
    repo = RunsRepository(db)
    first = _run_id(db, manifest_hash="hash-a")
    second = _run_id(db, manifest_hash="hash-b")
    assert [row.run_id for row in repo.list_all()] == [second, first]


def test_run_files_enqueue_many_counts_only_new_rows(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    subtitle_files = SubtitleFilesRepository(db)
    file_a = subtitle_files.upsert(_file_row(opensubtitles_file_id="1", rel_path="a/1.xml"))
    file_b = subtitle_files.upsert(_file_row(opensubtitles_file_id="2", rel_path="a/2.xml"))
    repo = RunFilesRepository(db)

    assert repo.enqueue_many(run_id, [file_a]) == 1
    assert repo.enqueue_many(run_id, [file_a, file_b]) == 1


def test_run_files_iter_pending_excludes_terminal_statuses_and_orders_by_rel_path(
    db: sqlite3.Connection,
) -> None:
    run_id = _run_id(db)
    subtitle_files = SubtitleFilesRepository(db)
    file_b = subtitle_files.upsert(_file_row(opensubtitles_file_id="2", rel_path="b/2.xml"))
    file_a = subtitle_files.upsert(_file_row(opensubtitles_file_id="1", rel_path="a/1.xml"))
    file_c = subtitle_files.upsert(_file_row(opensubtitles_file_id="3", rel_path="c/3.xml"))
    repo = RunFilesRepository(db)
    repo.enqueue_many(run_id, [file_a, file_b, file_c])
    repo.mark_done(run_id, file_c)

    pending = list(repo.iter_pending(run_id))
    assert [row.file_id for row in pending] == [file_a, file_b]


def test_run_files_mark_started_sets_started_at_once(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    repo = RunFilesRepository(db)
    repo.enqueue_many(run_id, [file_id])

    repo.mark_started(run_id, file_id)
    first = db.execute(
        "SELECT started_at FROM run_files WHERE run_id = ? AND file_id = ?", (run_id, file_id)
    ).fetchone()["started_at"]
    assert first is not None

    repo.mark_started(run_id, file_id)
    second = db.execute(
        "SELECT started_at FROM run_files WHERE run_id = ? AND file_id = ?", (run_id, file_id)
    ).fetchone()["started_at"]
    assert second == first


def test_run_files_mark_error_keeps_the_cursor(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    repo = RunFilesRepository(db)
    repo.enqueue_many(run_id, [file_id])
    repo.advance(run_id, file_id, last_sentence_index=9, last_sentence_id="s9", chunks_done=1)

    repo.mark_error(run_id, file_id, "boom")

    row = repo.get(run_id, file_id)
    assert row is not None
    assert row.status is FileStatus.ERROR
    assert row.error == "boom"
    assert row.last_sentence_index == 9
    assert row.chunks_done == 1


def test_run_files_reset_clears_cursor_across_runs(db: sqlite3.Connection) -> None:
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    run_a = _run_id(db, manifest_hash="hash-a")
    run_b = _run_id(db, manifest_hash="hash-b")
    repo = RunFilesRepository(db)
    repo.enqueue_many(run_a, [file_id])
    repo.enqueue_many(run_b, [file_id])
    repo.advance(run_a, file_id, last_sentence_index=5, last_sentence_id="s5", chunks_done=1)
    repo.mark_started(run_b, file_id)

    affected = repo.reset(file_id)

    assert affected == 2
    for run_id in (run_a, run_b):
        row = repo.get(run_id, file_id)
        assert row is not None
        assert row.status is FileStatus.PENDING
        assert row.last_sentence_index is None
        assert row.chunks_done == 0


def test_run_files_advance_flips_pending_to_in_progress(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    repo = RunFilesRepository(db)
    repo.enqueue_many(run_id, [file_id])

    repo.advance(run_id, file_id, last_sentence_index=1, last_sentence_id="s1", chunks_done=1)

    row = repo.get(run_id, file_id)
    assert row is not None
    assert row.status is FileStatus.IN_PROGRESS
    assert row.last_sentence_index == 1
    assert row.last_sentence_id == "s1"


def test_run_files_progress_reports_every_status_with_zeros(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    RunFilesRepository(db).enqueue_many(run_id, [file_id])

    progress = RunFilesRepository(db).progress(run_id)

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


def test_results_insert_ignore_is_idempotent(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    RunFilesRepository(db).enqueue_many(run_id, [file_id])
    repo = ResultsRepository(db)
    row = _result_row(run_id=run_id, file_id=file_id)

    assert repo.insert_ignore(row) is True
    assert repo.insert_ignore(row) is False
    assert repo.count(run_id) == 1


def test_results_payload_round_trips_through_json(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    RunFilesRepository(db).enqueue_many(run_id, [file_id])
    repo = ResultsRepository(db)
    repo.insert_ignore(
        _result_row(run_id=run_id, file_id=file_id, payload={"matched": True, "n": 3})
    )

    matches = list(repo.iter_matches(run_id))
    assert len(matches) == 1
    assert matches[0].payload == {"matched": True, "n": 3}


def test_results_delete_for_file_spans_every_run(db: sqlite3.Connection) -> None:
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    run_a = _run_id(db, manifest_hash="hash-a")
    run_b = _run_id(db, manifest_hash="hash-b")
    RunFilesRepository(db).enqueue_many(run_a, [file_id])
    RunFilesRepository(db).enqueue_many(run_b, [file_id])
    repo = ResultsRepository(db)
    repo.insert_ignore(_result_row(run_id=run_a, file_id=file_id, chunk_index=0))
    repo.insert_ignore(_result_row(run_id=run_b, file_id=file_id, chunk_index=0))

    deleted = repo.delete_for_file(file_id)

    assert deleted == 2
    assert repo.count(run_a) == 0
    assert repo.count(run_b) == 0


def test_results_count_matched_only(db: sqlite3.Connection) -> None:
    run_id = _run_id(db)
    file_id = SubtitleFilesRepository(db).upsert(_file_row())
    RunFilesRepository(db).enqueue_many(run_id, [file_id])
    repo = ResultsRepository(db)
    repo.insert_ignore(_result_row(run_id=run_id, file_id=file_id, chunk_index=0, matched=True))
    repo.insert_ignore(_result_row(run_id=run_id, file_id=file_id, chunk_index=1, matched=False))

    assert repo.count(run_id) == 2
    assert repo.count(run_id, matched_only=True) == 1
