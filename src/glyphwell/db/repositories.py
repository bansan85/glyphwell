"""Typed access to tables.

The rest of the code never builds SQL directly: it goes through these repositories, which
translate SQLite rows into value objects. This is also the only place where the resume
invariants translate into queries (``INSERT OR IGNORE``, deterministic ordering, one
transaction per chunk).

STATUS: `CorpusDownloadsRepository` is implemented; the rest is still stubs, whose
signatures and value objects are final (see "Current scope" in CLAUDE.md).
"""

import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from glyphwell.types import (
    ImdbId,
    JsonObject,
    LanguageCode,
    OpenSubtitlesFileId,
    OpusVersion,
    Sha256,
)

__all__ = [
    "CorpusDownloadRow",
    "CorpusDownloadsRepository",
    "DownloadStatus",
    "FileStatus",
    "ResultRow",
    "ResultsRepository",
    "RunFileRow",
    "RunFilesRepository",
    "RunRow",
    "RunStatus",
    "RunsRepository",
    "SubtitleFileRow",
    "SubtitleFilesRepository",
    "TitleRow",
    "TitlesRepository",
]


class RunStatus(StrEnum):
    """Life cycle of a search."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class FileStatus(StrEnum):
    """Life cycle of a file within a search.

    ``IN_PROGRESS`` is a legitimate state after an interruption: the cursor
    (`RunFileRow.last_sentence_index`) stays consistent and resuming picks up from there.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"


class DownloadStatus(StrEnum):
    """Life cycle of a corpus acquisition.

    There is no ``extracted`` state: the archive is never decompressed.
    """

    PENDING = "pending"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, kw_only=True)
class TitleRow:
    """A row of `titles`."""

    imdb_id: ImdbId
    title_type: str | None
    primary_title: str | None
    original_title: str | None
    start_year: int | None
    end_year: int | None
    is_adult: bool
    runtime_minutes: int | None
    parent_imdb_id: ImdbId | None
    season_number: int | None
    episode_number: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SubtitleFileRow:
    """A row of `subtitle_files`."""

    file_id: int
    opus_version: OpusVersion
    language: LanguageCode
    imdb_id: ImdbId
    opensubtitles_file_id: OpenSubtitlesFileId
    rel_path: str
    year: int | None
    sha256: Sha256 | None
    size_bytes: int | None
    sentence_count: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunRow:
    """A row of `runs`."""

    run_id: int
    manifest_path: str
    manifest_hash: Sha256
    model: str
    status: RunStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class RunFileRow:
    """A row of `run_files`: state of a file within a search.

    `last_sentence_index` is the resume cursor; `None` means "not started yet".
    """

    run_id: int
    file_id: int
    status: FileStatus
    file_sha256: Sha256 | None
    last_sentence_index: int | None
    last_sentence_id: str | None
    chunks_done: int
    error: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultRow:
    """A row of `results`: the model's response for a chunk."""

    result_id: int
    run_id: int
    file_id: int
    chunk_index: int
    first_sentence_index: int
    last_sentence_index: int
    matched: bool
    payload: JsonObject | None
    model: str
    latency_ms: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusDownloadRow:
    """A row of `corpus_downloads`: traceability of an acquisition.

    `download_id` is `None` until the row has been written, which makes the object usable
    both for insertion and for reading.
    """

    download_id: int | None = None
    opus_corpus: str
    opus_version: OpusVersion
    language: LanguageCode
    url: str | None
    archive_path: str | None
    sha256: Sha256 | None
    status: DownloadStatus
    downloaded_at: str | None = None
    verified_at: str | None = None


@dataclass(frozen=True, slots=True)
class TitlesRepository:
    """Reading and writing `titles`."""

    conn: sqlite3.Connection

    def get(self, imdb_id: ImdbId) -> TitleRow | None:
        """Returns the title, or `None` if it has not been imported."""
        raise NotImplementedError

    def upsert_many(self, rows: Sequence[TitleRow]) -> int:
        """Inserts or updates a batch of titles, and returns the number of rows written."""
        raise NotImplementedError

    def count(self) -> int:
        """Number of known titles."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SubtitleFilesRepository:
    """Catalog of corpus files."""

    conn: sqlite3.Connection

    def upsert(self, row: SubtitleFileRow) -> int:
        """Inserts or updates a file, and returns its `file_id`."""
        raise NotImplementedError

    def get_by_path(
        self,
        *,
        opus_version: OpusVersion,
        language: LanguageCode,
        rel_path: str,
    ) -> SubtitleFileRow | None:
        """Finds a file by its natural key."""
        raise NotImplementedError

    def set_hash(self, file_id: int, sha256: Sha256, *, size_bytes: int) -> None:
        """Records a file's checksum."""
        raise NotImplementedError

    def iter_stale(self) -> Iterator[SubtitleFileRow]:
        """Files whose checksum is missing or stale, to be rehashed."""
        raise NotImplementedError

    def count(self) -> int:
        """Number of cataloged files."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RunsRepository:
    """Life cycle of searches."""

    conn: sqlite3.Connection

    def create(
        self,
        *,
        manifest_path: str,
        manifest_hash: Sha256,
        manifest_snapshot: str,
        model: str,
    ) -> int:
        """Creates a search and returns its `run_id`."""
        raise NotImplementedError

    def get(self, run_id: int) -> RunRow | None:
        """Returns a search, or `None`."""
        raise NotImplementedError

    def find_by_hash(self, manifest_hash: Sha256) -> Sequence[RunRow]:
        """Searches already launched for this manifest, most recent first."""
        raise NotImplementedError

    def set_status(self, run_id: int, status: RunStatus) -> None:
        """Changes the status of a search."""
        raise NotImplementedError

    def list_all(self) -> Sequence[RunRow]:
        """All searches, most recent first."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RunFilesRepository:
    """Work queue and resume cursors."""

    conn: sqlite3.Connection

    def enqueue_many(self, run_id: int, file_ids: Sequence[int]) -> int:
        """Adds files to the queue, without overwriting those already present.

        Idempotent: reusable to complete the queue of an existing run when new files
        appear in the corpus.
        """
        raise NotImplementedError

    def iter_pending(self, run_id: int) -> Iterator[RunFileRow]:
        """Unfinished files, in the deterministic ``ORDER BY rel_path`` order.

        This ordering is what makes `chunk_index` stable across runs: without it, resuming
        would not point to the same chunks.
        """
        raise NotImplementedError

    def get(self, run_id: int, file_id: int) -> RunFileRow | None:
        """State of a file within a search."""
        raise NotImplementedError

    def mark_started(self, run_id: int, file_id: int) -> None:
        """Sets a file to `IN_PROGRESS`."""
        raise NotImplementedError

    def mark_done(self, run_id: int, file_id: int) -> None:
        """Sets a file to `DONE`."""
        raise NotImplementedError

    def mark_error(self, run_id: int, file_id: int, error: str) -> None:
        """Sets a file to `ERROR` while keeping its cursor, so resuming stays possible."""
        raise NotImplementedError

    def reset(self, file_id: int) -> int:
        """Resets a file to `PENDING` across all searches and clears its cursor.

        Called when the file's checksum has changed. Only touches this file: the rest of
        each search is preserved.
        """
        raise NotImplementedError

    def progress(self, run_id: int) -> dict[FileStatus, int]:
        """Counts files by status, for ``search status``."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ResultsRepository:
    """Results produced by the model."""

    conn: sqlite3.Connection

    def insert_ignore(self, row: ResultRow) -> bool:
        """Inserts a result, with no effect if it already exists.

        Returns true if a row was written. A duplicate is not an error: it is the normal
        case when a chunk is replayed after an interruption.
        """
        raise NotImplementedError

    def delete_for_file(self, file_id: int) -> int:
        """Deletes all results for a file, across every search.

        Used for invalidation when the subtitle's content has changed.
        """
        raise NotImplementedError

    def iter_matches(self, run_id: int) -> Iterator[ResultRow]:
        """Positive results of a search, for export."""
        raise NotImplementedError

    def count(self, run_id: int, *, matched_only: bool = False) -> int:
        """Number of results of a search."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class CorpusDownloadsRepository:
    """Traceability of corpus downloads.

    One row per ``(corpus, version, language)``. It is written as ``pending`` *before* the
    transfer: a missing database should make ``corpus fetch`` fail right away, not after
    several dozen GB.
    """

    conn: sqlite3.Connection

    def upsert(self, row: CorpusDownloadRow) -> int:
        """Inserts or updates an acquisition, and returns its `download_id`.

        A checksum that is already known is never erased by a write that does not carry
        one: `sha256` can only be computed for free during a complete download.
        """
        cursor = self.conn.execute(
            "INSERT INTO corpus_downloads"
            " (opus_corpus, opus_version, language, url, archive_path, sha256, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (opus_corpus, opus_version, language) DO UPDATE SET"
            "     url = coalesce(excluded.url, corpus_downloads.url),"
            "     archive_path = coalesce(excluded.archive_path, corpus_downloads.archive_path),"
            "     sha256 = coalesce(excluded.sha256, corpus_downloads.sha256),"
            "     status = excluded.status"
            " RETURNING download_id",
            (
                row.opus_corpus,
                row.opus_version,
                row.language,
                row.url,
                row.archive_path,
                row.sha256,
                row.status.value,
            ),
        )
        return int(cursor.fetchone()["download_id"])

    def get(
        self,
        *,
        opus_corpus: str,
        opus_version: OpusVersion,
        language: LanguageCode,
    ) -> CorpusDownloadRow | None:
        """Finds an acquisition by its natural key."""
        found = self.conn.execute(
            "SELECT * FROM corpus_downloads"
            " WHERE opus_corpus = ? AND opus_version = ? AND language = ?",
            (opus_corpus, opus_version, language),
        ).fetchone()
        return None if found is None else _to_download_row(found)

    def mark(
        self,
        download_id: int,
        status: DownloadStatus,
        *,
        sha256: Sha256 | None = None,
        archive_path: str | None = None,
        verified: bool = False,
    ) -> None:
        """Advances an acquisition.

        Args:
            download_id: acquisition concerned.
            status: new state. ``downloaded`` timestamps `downloaded_at`.
            sha256: checksum, if it could be computed.
            archive_path: path of the archive obtained.
            verified: the archive has been opened and its members counted.
        """
        self.conn.execute(
            "UPDATE corpus_downloads SET"
            "     status = ?,"
            "     sha256 = coalesce(?, sha256),"
            "     archive_path = coalesce(?, archive_path),"
            "     downloaded_at = CASE WHEN ? = 'downloaded'"
            "         THEN datetime('now') ELSE downloaded_at END,"
            "     verified_at = CASE WHEN ? THEN datetime('now') ELSE verified_at END"
            " WHERE download_id = ?",
            (status.value, sha256, archive_path, status.value, int(verified), download_id),
        )

    def iter_all(self) -> Iterator[CorpusDownloadRow]:
        """All acquisitions, from most recent to oldest."""
        for found in self.conn.execute(
            "SELECT * FROM corpus_downloads ORDER BY downloaded_at DESC, download_id DESC"
        ):
            yield _to_download_row(found)


def _to_download_row(row: sqlite3.Row) -> CorpusDownloadRow:
    """Translates a row of `corpus_downloads`."""
    return CorpusDownloadRow(
        download_id=int(row["download_id"]),
        opus_corpus=str(row["opus_corpus"]),
        opus_version=str(row["opus_version"]),
        language=str(row["language"]),
        url=None if row["url"] is None else str(row["url"]),
        archive_path=None if row["archive_path"] is None else str(row["archive_path"]),
        sha256=None if row["sha256"] is None else str(row["sha256"]),
        status=DownloadStatus(row["status"]),
        downloaded_at=None if row["downloaded_at"] is None else str(row["downloaded_at"]),
        verified_at=None if row["verified_at"] is None else str(row["verified_at"]),
    )
