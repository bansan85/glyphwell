"""Traceability of corpus acquisitions."""

import sqlite3

from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
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
