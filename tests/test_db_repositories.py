"""Traceability of corpus acquisitions, titles, and IMDb dataset imports."""

import sqlite3

from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
    EpisodeLink,
    ImportRow,
    ImportSource,
    ImportsRepository,
    TitleRow,
    TitlesRepository,
)


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
