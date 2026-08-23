"""Building a search's work queue.

The planner translates the manifest's ``select`` filters into a set of files, then
materializes that set into `run_files`. Materializing the queue rather than recomputing it
every round has two virtues: progress is measurable, and a resume picks up exactly the
same list even if the corpus has grown in the meantime.

**Order is an invariant, not a detail.** Traversal is always ``ORDER BY
subtitle_files.rel_path``. Without this fixed order, `chunk_index` would not designate the
same sentence range from one run to the next, and the uniqueness constraint on `results`
would stop guaranteeing idempotence.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from glyphwell.db.repositories import FileStatus, RunFilesRepository
from glyphwell.errors import DatabaseError
from glyphwell.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterator

    from glyphwell.manifest.model import SelectConfig

__all__ = ["PlannedFile", "enqueue", "iter_work", "plan_size"]

_log = get_logger(__name__)

_ENQUEUE_BATCH_SIZE: Final = 5_000
"""Files per `enqueue_many` call, to avoid one call carrying the whole corpus."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedFile:
    """A file to process, with what is needed to read and describe it.

    Groups into one object what would otherwise come from three queries: the file, its
    title, and its cursor.
    """

    file_id: int
    rel_path: str
    imdb_id: str
    sentence_count: int | None
    last_sentence_index: int | None
    chunks_done: int


def enqueue(conn: sqlite3.Connection, *, run_id: int, select: "SelectConfig") -> int:
    """Fills `run_files` for a search and returns the number of files added.

    Idempotent: can be re-run to complete the queue of an existing search when new files
    have appeared in the corpus, without touching files already processed.

    Filters on the title require the IMDb datasets to have been imported. Files whose
    identifier remains unresolved are discarded, and their count is logged — otherwise a
    corpus indexed without metadata would produce an empty queue with no explanation.

    Raises:
        DatabaseError: write failed.
    """
    query, params = _matching_query(select)
    repo = RunFilesRepository(conn)
    added = 0
    batch: list[int] = []
    try:
        for row in conn.execute(query, params):
            batch.append(int(row["file_id"]))
            if len(batch) >= _ENQUEUE_BATCH_SIZE:
                added += repo.enqueue_many(run_id, batch)
                batch.clear()
        if batch:
            added += repo.enqueue_many(run_id, batch)
    except sqlite3.Error as exc:
        message = f"failed to enqueue files for run {run_id}: {exc}"
        raise DatabaseError(message) from exc

    unresolved_query, unresolved_params = _unresolved_query(select)
    unresolved = int(conn.execute(unresolved_query, unresolved_params).fetchone()["n"])
    if unresolved:
        _log.warning("%d file(s) excluded from the queue: IMDb id not resolved", unresolved)
    return added


def iter_work(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    limit: int | None = None,
) -> "Iterator[PlannedFile]":
    """Yields unfinished files, in the plan's deterministic order.

    Generator: the queue can hold hundreds of thousands of entries. Issues its own bulk
    join rather than composing `RunFilesRepository.iter_pending` with a lookup per row,
    which would be an N+1 query pattern at this scale.

    Args:
        conn: database connection.
        run_id: search concerned.
        limit: stops after this number of files, for a quick trial.

    Yields:
        Files to process, ``ORDER BY rel_path``.
    """
    query = (
        "SELECT rf.file_id, sf.rel_path, sf.imdb_id, sf.sentence_count,"
        "       rf.last_sentence_index, rf.chunks_done"
        " FROM run_files rf JOIN subtitle_files sf ON sf.file_id = rf.file_id"
        " WHERE rf.run_id = ? AND rf.status IN ('pending', 'in_progress')"
        " ORDER BY sf.rel_path"
    )
    for count, row in enumerate(conn.execute(query, (run_id,))):
        if limit is not None and count >= limit:
            break
        yield PlannedFile(
            file_id=int(row["file_id"]),
            rel_path=str(row["rel_path"]),
            imdb_id=str(row["imdb_id"]),
            sentence_count=None if row["sentence_count"] is None else int(row["sentence_count"]),
            last_sentence_index=(
                None if row["last_sentence_index"] is None else int(row["last_sentence_index"])
            ),
            chunks_done=int(row["chunks_done"]),
        )


def plan_size(conn: sqlite3.Connection, run_id: int) -> tuple[int, int]:
    """Returns ``(files done, files planned)`` for displaying progress."""
    progress = RunFilesRepository(conn).progress(run_id)
    return progress[FileStatus.DONE], sum(progress.values())


def _select_clauses(select: "SelectConfig") -> tuple[list[str], list[object]]:
    """Shared corpus-level ``WHERE`` clauses: language and an explicit id list.

    Kept separate from the title-dependent clauses (`title_types`, `years`), which only
    make sense once a title row is known to exist at all.
    """
    clauses: list[str] = []
    params: list[object] = []
    if select.languages:
        clauses.append(f"sf.language IN ({_placeholders(len(select.languages))})")
        params.extend(select.languages)
    if select.imdb_ids is not None:
        clauses.append(f"sf.imdb_id IN ({_placeholders(len(select.imdb_ids))})")
        params.extend(select.imdb_ids)
    return clauses, params


def _matching_query(select: "SelectConfig") -> tuple[str, list[object]]:
    """Files whose title resolves and satisfies every filter."""
    clauses, params = _select_clauses(select)
    if select.title_types:
        clauses.append(f"t.title_type IN ({_placeholders(len(select.title_types))})")
        params.extend(select.title_types)
    if select.years.min is not None:
        clauses.append("t.start_year >= ?")
        params.append(select.years.min)
    if select.years.max is not None:
        clauses.append("t.start_year <= ?")
        params.append(select.years.max)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        f"SELECT sf.file_id FROM subtitle_files sf JOIN titles t ON t.imdb_id = sf.imdb_id{where}"
    )
    return query, params


def _unresolved_query(select: "SelectConfig") -> tuple[str, list[object]]:
    """Files matching the corpus-level filters whose title does not resolve at all."""
    clauses, params = _select_clauses(select)
    clauses.append("t.imdb_id IS NULL")
    where = f" WHERE {' AND '.join(clauses)}"
    query = (
        "SELECT COUNT(*) AS n FROM subtitle_files sf"
        f" LEFT JOIN titles t ON t.imdb_id = sf.imdb_id{where}"
    )
    return query, params


def _placeholders(count: int) -> str:
    """``?, ?, ...`` for a dynamically-sized ``IN (...)`` clause."""
    return ", ".join(["?"] * count)
