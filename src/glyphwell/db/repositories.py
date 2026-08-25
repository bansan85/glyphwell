"""Typed access to tables.

The rest of the code never builds SQL directly: it goes through these repositories, which
translate SQLite rows into value objects. This is also the only place where the resume
invariants translate into queries (``INSERT OR IGNORE``, deterministic ordering, one
transaction per chunk).
"""

import json
import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from pydantic import TypeAdapter

from glyphwell.types import (
    ImdbId,
    JsonObject,
    LanguageCode,
    OpenSubtitlesFileId,
    OpusVersion,
    Sha256,
)

_JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)

__all__ = [
    "CorpusDownloadRow",
    "CorpusDownloadsRepository",
    "DownloadStatus",
    "EpisodeLink",
    "FileStatus",
    "ImportRow",
    "ImportSource",
    "ImportsRepository",
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


class ImportSource(StrEnum):
    """Which IMDb dataset an `imports` row traces."""

    BASICS = "imdb_basics"
    EPISODE = "imdb_episode"


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
class EpisodeLink:
    """An episode's attachment to its series, as carried by ``title.episode.tsv``.

    Deliberately separate from `TitleRow`: attaching an episode only ever touches three
    columns of an already-existing row. Routing it through `TitleRow` and `upsert_many`
    would force every other column — starting with the non-nullable `is_adult` — back to
    a default, silently erasing what `import_basics` had already written.
    """

    imdb_id: ImdbId
    parent_imdb_id: ImdbId
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


@dataclass(frozen=True, slots=True, kw_only=True)
class ImportRow:
    """A row of `imports`: traceability of an IMDb dataset import.

    `import_id` is `None` until the row has been written, mirroring `CorpusDownloadRow`.
    """

    import_id: int | None = None
    source: ImportSource
    file_name: str
    released_at: str | None = None
    row_count: int | None = None
    imported_at: str | None = None


@dataclass(frozen=True, slots=True)
class TitlesRepository:
    """Reading and writing `titles`."""

    conn: sqlite3.Connection

    def get(self, imdb_id: ImdbId) -> TitleRow | None:
        """Returns the title, or `None` if it has not been imported."""
        found = self.conn.execute("SELECT * FROM titles WHERE imdb_id = ?", (imdb_id,)).fetchone()
        return None if found is None else _to_title_row(found)

    def upsert_many(self, rows: Sequence[TitleRow]) -> int:
        """Inserts or updates a batch of titles, and returns the number of rows written.

        Used by `import_basics`, which always carries authoritative values for every
        column it knows about. A column left `None` (the parent link, filled in later by
        `import_episodes`) is preserved rather than overwritten with `NULL`, via the same
        ``coalesce(excluded, ...)`` pattern as `CorpusDownloadsRepository.upsert`.
        """
        if not rows:
            return 0
        cursor = self.conn.executemany(
            "INSERT INTO titles"
            " (imdb_id, title_type, primary_title, original_title, start_year, end_year,"
            "  is_adult, runtime_minutes, parent_imdb_id, season_number, episode_number)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (imdb_id) DO UPDATE SET"
            "     title_type = coalesce(excluded.title_type, titles.title_type),"
            "     primary_title = coalesce(excluded.primary_title, titles.primary_title),"
            "     original_title = coalesce(excluded.original_title, titles.original_title),"
            "     start_year = coalesce(excluded.start_year, titles.start_year),"
            "     end_year = coalesce(excluded.end_year, titles.end_year),"
            "     is_adult = excluded.is_adult,"
            "     runtime_minutes = coalesce(excluded.runtime_minutes, titles.runtime_minutes),"
            "     parent_imdb_id = coalesce(excluded.parent_imdb_id, titles.parent_imdb_id),"
            "     season_number = coalesce(excluded.season_number, titles.season_number),"
            "     episode_number = coalesce(excluded.episode_number, titles.episode_number)",
            [
                (
                    row.imdb_id,
                    row.title_type,
                    row.primary_title,
                    row.original_title,
                    row.start_year,
                    row.end_year,
                    int(row.is_adult),
                    row.runtime_minutes,
                    row.parent_imdb_id,
                    row.season_number,
                    row.episode_number,
                )
                for row in rows
            ],
        )
        return cursor.rowcount

    def set_episode_links_many(self, links: Sequence[EpisodeLink]) -> int:
        """Attaches episodes to their series, and returns the number of rows updated.

        A plain ``UPDATE``, not an upsert: the episode's own row must already exist —
        `import_episodes` runs after `import_basics` for exactly that reason. This also
        keeps the write from touching any other column of `titles` (see `EpisodeLink`).
        """
        if not links:
            return 0
        cursor = self.conn.executemany(
            "UPDATE titles SET parent_imdb_id = ?, season_number = ?, episode_number = ?"
            " WHERE imdb_id = ?",
            [
                (link.parent_imdb_id, link.season_number, link.episode_number, link.imdb_id)
                for link in links
            ],
        )
        return cursor.rowcount

    def count(self) -> int:
        """Number of known titles."""
        found = self.conn.execute("SELECT COUNT(*) AS n FROM titles").fetchone()
        return int(found["n"])


@dataclass(frozen=True, slots=True)
class SubtitleFilesRepository:
    """Catalog of corpus files."""

    conn: sqlite3.Connection

    def upsert(self, row: SubtitleFileRow) -> int:
        """Inserts or updates a file, and returns its `file_id`.

        Matched on the natural key ``(opus_version, language, rel_path)`` — `row.file_id`
        is never read: it only exists so the same dataclass can represent a row freshly
        read back from the database. `imdb_id`/`opensubtitles_file_id` are overwritten
        unconditionally (always freshly re-derived from `rel_path`); the remaining
        nullable columns are coalesced, so a later partial write (for example backfilling
        `sentence_count` after a first full read) never blanks out what an earlier pass
        already knew.
        """
        cursor = self.conn.execute(
            "INSERT INTO subtitle_files"
            " (opus_version, language, imdb_id, opensubtitles_file_id, rel_path,"
            "  year, size_bytes, sentence_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (opus_version, language, rel_path) DO UPDATE SET"
            "     imdb_id = excluded.imdb_id,"
            "     opensubtitles_file_id = excluded.opensubtitles_file_id,"
            "     year = coalesce(excluded.year, subtitle_files.year),"
            "     size_bytes = coalesce(excluded.size_bytes, subtitle_files.size_bytes),"
            "     sentence_count ="
            "         coalesce(excluded.sentence_count, subtitle_files.sentence_count),"
            "     updated_at = datetime('now')"
            " RETURNING file_id",
            (
                row.opus_version,
                row.language,
                row.imdb_id,
                row.opensubtitles_file_id,
                row.rel_path,
                row.year,
                row.size_bytes,
                row.sentence_count,
            ),
        )
        return int(cursor.fetchone()["file_id"])

    def get(self, file_id: int) -> SubtitleFileRow | None:
        """Finds a file by its surrogate key."""
        found = self.conn.execute(
            "SELECT * FROM subtitle_files WHERE file_id = ?", (file_id,)
        ).fetchone()
        return None if found is None else _to_subtitle_file_row(found)

    def get_by_path(
        self,
        *,
        opus_version: OpusVersion,
        language: LanguageCode,
        rel_path: str,
    ) -> SubtitleFileRow | None:
        """Finds a file by its natural key."""
        found = self.conn.execute(
            "SELECT * FROM subtitle_files WHERE opus_version = ? AND language = ? AND rel_path = ?",
            (opus_version, language, rel_path),
        ).fetchone()
        return None if found is None else _to_subtitle_file_row(found)

    def count(self) -> int:
        """Number of cataloged files."""
        found = self.conn.execute("SELECT COUNT(*) AS n FROM subtitle_files").fetchone()
        return int(found["n"])


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
        """Creates a search and returns its `run_id`.

        `status` is left out: the schema defaults it to ``pending``.
        """
        cursor = self.conn.execute(
            "INSERT INTO runs (manifest_path, manifest_hash, manifest_snapshot, model)"
            " VALUES (?, ?, ?, ?)",
            (manifest_path, manifest_hash, manifest_snapshot, model),
        )
        return int(cursor.lastrowid) if cursor.lastrowid is not None else 0

    def get(self, run_id: int) -> RunRow | None:
        """Returns a search, or `None`."""
        found = self.conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if found is None else _to_run_row(found)

    def get_manifest_snapshot(self, run_id: int) -> str | None:
        """Returns the archived YAML source of a search's manifest, or `None`.

        A dedicated lookup rather than a `RunRow` field: the snapshot is the full YAML
        text, and `list_all`/`find_by_hash` callers (a status listing, a resume check)
        have no use for loading it on every row.
        """
        found = self.conn.execute(
            "SELECT manifest_snapshot FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return None if found is None else str(found["manifest_snapshot"])

    def find_by_hash(self, manifest_hash: Sha256) -> Sequence[RunRow]:
        """Searches already launched for this manifest, most recent first."""
        rows = self.conn.execute(
            "SELECT * FROM runs WHERE manifest_hash = ? ORDER BY created_at DESC, run_id DESC",
            (manifest_hash,),
        ).fetchall()
        return [_to_run_row(row) for row in rows]

    def set_status(self, run_id: int, status: RunStatus) -> None:
        """Changes the status of a search.

        `finished_at` is derived from the *new* status, not merely preserved: a status
        that regresses out of a terminal one (for example a corrective re-run) does not
        leave a stale `finished_at` behind.
        """
        self.conn.execute(
            "UPDATE runs SET"
            "     status = ?,"
            "     updated_at = datetime('now'),"
            "     finished_at = CASE WHEN ? IN ('done', 'failed')"
            "         THEN datetime('now') ELSE NULL END"
            " WHERE run_id = ?",
            (status.value, status.value, run_id),
        )

    def list_all(self) -> Sequence[RunRow]:
        """All searches, most recent first."""
        rows = self.conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC, run_id DESC"
        ).fetchall()
        return [_to_run_row(row) for row in rows]


@dataclass(frozen=True, slots=True)
class RunFilesRepository:
    """Work queue and resume cursors."""

    conn: sqlite3.Connection

    def enqueue_many(self, run_id: int, file_ids: Sequence[int]) -> int:
        """Adds files to the queue, without overwriting those already present.

        Idempotent: reusable to complete the queue of an existing run when new files
        appear in the corpus.
        """
        if not file_ids:
            return 0
        cursor = self.conn.executemany(
            "INSERT OR IGNORE INTO run_files (run_id, file_id) VALUES (?, ?)",
            [(run_id, file_id) for file_id in file_ids],
        )
        return cursor.rowcount

    def iter_pending(self, run_id: int) -> Iterator[RunFileRow]:
        """Unfinished files, in the deterministic ``ORDER BY rel_path`` order.

        This ordering is what makes `chunk_index` stable across runs: without it, resuming
        would not point to the same chunks. "Unfinished" excludes `error` on purpose: a
        broken file needs a deliberate recovery action, not a silent retry on every resume.
        """
        for found in self.conn.execute(
            "SELECT run_files.* FROM run_files"
            " JOIN subtitle_files ON subtitle_files.file_id = run_files.file_id"
            " WHERE run_files.run_id = ? AND run_files.status IN ('pending', 'in_progress')"
            " ORDER BY subtitle_files.rel_path",
            (run_id,),
        ):
            yield _to_run_file_row(found)

    def get(self, run_id: int, file_id: int) -> RunFileRow | None:
        """State of a file within a search."""
        found = self.conn.execute(
            "SELECT * FROM run_files WHERE run_id = ? AND file_id = ?", (run_id, file_id)
        ).fetchone()
        return None if found is None else _to_run_file_row(found)

    def mark_started(self, run_id: int, file_id: int) -> None:
        """Sets a file to `IN_PROGRESS`.

        `started_at` is set once (`coalesce`), so repeated resumes of the same file do
        not keep pushing it forward.
        """
        self.conn.execute(
            "UPDATE run_files SET"
            "     status = 'in_progress',"
            "     started_at = coalesce(started_at, datetime('now')),"
            "     updated_at = datetime('now')"
            " WHERE run_id = ? AND file_id = ?",
            (run_id, file_id),
        )

    def mark_done(self, run_id: int, file_id: int) -> None:
        """Sets a file to `DONE`."""
        self.conn.execute(
            "UPDATE run_files SET status = 'done', updated_at = datetime('now')"
            " WHERE run_id = ? AND file_id = ?",
            (run_id, file_id),
        )

    def mark_error(self, run_id: int, file_id: int, error: str) -> None:
        """Sets a file to `ERROR` while keeping its cursor, so resuming stays possible."""
        self.conn.execute(
            "UPDATE run_files SET status = 'error', error = ?, updated_at = datetime('now')"
            " WHERE run_id = ? AND file_id = ?",
            (error, run_id, file_id),
        )

    def advance(
        self,
        run_id: int,
        file_id: int,
        *,
        last_sentence_index: int,
        last_sentence_id: str,
        chunks_done: int,
    ) -> None:
        """Advances a file's resume cursor after a chunk has been committed.

        Also flips ``pending`` to ``in_progress`` on the first advance, for a file
        processed inline without a separate `mark_started` call.
        """
        self.conn.execute(
            "UPDATE run_files SET"
            "     status = CASE WHEN status = 'pending' THEN 'in_progress' ELSE status END,"
            "     last_sentence_index = ?,"
            "     last_sentence_id = ?,"
            "     chunks_done = ?,"
            "     updated_at = datetime('now')"
            " WHERE run_id = ? AND file_id = ?",
            (last_sentence_index, last_sentence_id, chunks_done, run_id, file_id),
        )

    def progress(self, run_id: int) -> dict[FileStatus, int]:
        """Counts files by status, for ``search status``.

        Always returns all 5 statuses, zero-filled for those with no row, so a caller
        building a fixed-column report never needs a defensive `.get(...)`.
        """
        counts: dict[FileStatus, int] = dict.fromkeys(FileStatus, 0)
        for found in self.conn.execute(
            "SELECT status, COUNT(*) AS n FROM run_files WHERE run_id = ? GROUP BY status",
            (run_id,),
        ):
            counts[FileStatus(found["status"])] = int(found["n"])
        return counts


@dataclass(frozen=True, slots=True)
class ResultsRepository:
    """Results produced by the model."""

    conn: sqlite3.Connection

    def insert_ignore(self, row: ResultRow) -> bool:
        """Inserts a result, with no effect if it already exists.

        Returns true if a row was written. A duplicate is not an error: it is the normal
        case when a chunk is replayed after an interruption — this is exactly the signal
        `search.checkpoint.commit_chunk` uses to tell a new chunk from a replayed one.
        """
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO results"
            " (run_id, file_id, chunk_index, first_sentence_index, last_sentence_index,"
            "  matched, payload, model, latency_ms)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row.run_id,
                row.file_id,
                row.chunk_index,
                row.first_sentence_index,
                row.last_sentence_index,
                int(row.matched),
                None if row.payload is None else json.dumps(row.payload),
                row.model,
                row.latency_ms,
            ),
        )
        return cursor.rowcount > 0

    def iter_matches(self, run_id: int) -> Iterator[ResultRow]:
        """Positive results of a search, for export."""
        for found in self.conn.execute(
            "SELECT * FROM results WHERE run_id = ? AND matched = 1 ORDER BY file_id, chunk_index",
            (run_id,),
        ):
            yield _to_result_row(found)

    def count(self, run_id: int, *, matched_only: bool = False) -> int:
        """Number of results of a search."""
        query = "SELECT COUNT(*) AS n FROM results WHERE run_id = ?"
        if matched_only:
            query += " AND matched = 1"
        found = self.conn.execute(query, (run_id,)).fetchone()
        return int(found["n"])


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


@dataclass(frozen=True, slots=True)
class ImportsRepository:
    """Traceability of IMDb dataset imports, one row per completed `import_basics` or
    `import_episodes` run.
    """

    conn: sqlite3.Connection

    def record(self, row: ImportRow) -> int:
        """Logs a completed import and returns its `import_id`."""
        cursor = self.conn.execute(
            "INSERT INTO imports (source, file_name, released_at, row_count) VALUES (?, ?, ?, ?)",
            (row.source.value, row.file_name, row.released_at, row.row_count),
        )
        return int(cursor.lastrowid) if cursor.lastrowid is not None else 0

    def iter_all(self) -> Iterator[ImportRow]:
        """All imports, from most recent to oldest."""
        for found in self.conn.execute(
            "SELECT * FROM imports ORDER BY imported_at DESC, import_id DESC"
        ):
            yield _to_import_row(found)


def _to_title_row(row: sqlite3.Row) -> TitleRow:
    """Translates a row of `titles`."""
    return TitleRow(
        imdb_id=str(row["imdb_id"]),
        title_type=None if row["title_type"] is None else str(row["title_type"]),
        primary_title=None if row["primary_title"] is None else str(row["primary_title"]),
        original_title=None if row["original_title"] is None else str(row["original_title"]),
        start_year=None if row["start_year"] is None else int(row["start_year"]),
        end_year=None if row["end_year"] is None else int(row["end_year"]),
        is_adult=bool(row["is_adult"]),
        runtime_minutes=None if row["runtime_minutes"] is None else int(row["runtime_minutes"]),
        parent_imdb_id=None if row["parent_imdb_id"] is None else str(row["parent_imdb_id"]),
        season_number=None if row["season_number"] is None else int(row["season_number"]),
        episode_number=None if row["episode_number"] is None else int(row["episode_number"]),
    )


def _to_import_row(row: sqlite3.Row) -> ImportRow:
    """Translates a row of `imports`."""
    return ImportRow(
        import_id=int(row["import_id"]),
        source=ImportSource(row["source"]),
        file_name=str(row["file_name"]),
        released_at=None if row["released_at"] is None else str(row["released_at"]),
        row_count=None if row["row_count"] is None else int(row["row_count"]),
        imported_at=None if row["imported_at"] is None else str(row["imported_at"]),
    )


def _to_subtitle_file_row(row: sqlite3.Row) -> SubtitleFileRow:
    """Translates a row of `subtitle_files`."""
    return SubtitleFileRow(
        file_id=int(row["file_id"]),
        opus_version=str(row["opus_version"]),
        language=str(row["language"]),
        imdb_id=str(row["imdb_id"]),
        opensubtitles_file_id=str(row["opensubtitles_file_id"]),
        rel_path=str(row["rel_path"]),
        year=None if row["year"] is None else int(row["year"]),
        size_bytes=None if row["size_bytes"] is None else int(row["size_bytes"]),
        sentence_count=None if row["sentence_count"] is None else int(row["sentence_count"]),
    )


def _to_run_row(row: sqlite3.Row) -> RunRow:
    """Translates a row of `runs`."""
    return RunRow(
        run_id=int(row["run_id"]),
        manifest_path=str(row["manifest_path"]),
        manifest_hash=str(row["manifest_hash"]),
        model=str(row["model"]),
        status=RunStatus(row["status"]),
    )


def _to_run_file_row(row: sqlite3.Row) -> RunFileRow:
    """Translates a row of `run_files`."""
    return RunFileRow(
        run_id=int(row["run_id"]),
        file_id=int(row["file_id"]),
        status=FileStatus(row["status"]),
        last_sentence_index=(
            None if row["last_sentence_index"] is None else int(row["last_sentence_index"])
        ),
        last_sentence_id=None if row["last_sentence_id"] is None else str(row["last_sentence_id"]),
        chunks_done=int(row["chunks_done"]),
        error=None if row["error"] is None else str(row["error"]),
    )


def _to_result_row(row: sqlite3.Row) -> ResultRow:
    """Translates a row of `results`."""
    payload = row["payload"]
    return ResultRow(
        result_id=int(row["result_id"]),
        run_id=int(row["run_id"]),
        file_id=int(row["file_id"]),
        chunk_index=int(row["chunk_index"]),
        first_sentence_index=int(row["first_sentence_index"]),
        last_sentence_index=int(row["last_sentence_index"]),
        matched=bool(row["matched"]),
        payload=None if payload is None else _JSON_OBJECT_ADAPTER.validate_json(payload),
        model=str(row["model"]),
        latency_ms=None if row["latency_ms"] is None else int(row["latency_ms"]),
    )
