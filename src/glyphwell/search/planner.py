"""Building a search's work queue.

The planner translates the manifest's ``select`` filters into a set of files, matched
against the catalog database, then materializes that set into the run database's
`run_files`. Materializing the queue rather than recomputing it every round has two
virtues: progress is measurable, and a resume picks up exactly the same list even if the
corpus has grown in the meantime.

**Order is an invariant, not a detail.** Traversal is always ``ORDER BY
run_files.rel_path`` (a copy of the catalog's `subtitle_files.rel_path`, taken at enqueue
time — see `enqueue`). Without this fixed order, `chunk_index` would not designate the
same sentence range from one run to the next, and the uniqueness constraint on `results`
would stop guaranteeing idempotence.
"""

import itertools
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from glyphwell.db.repositories import FileStatus, RunFilesRepository
from glyphwell.errors import DatabaseError
from glyphwell.logging import get_logger
from glyphwell.search.dedup import Candidate, select_representative

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from glyphwell.manifest.model import SelectConfig

__all__ = ["PlannedFile", "enqueue", "iter_work", "plan_size"]

_log = get_logger(__name__)

_ENQUEUE_BATCH_SIZE: Final = 5_000
"""Files per page: one `SELECT` plus one `enqueue_many` transaction, to avoid one call
carrying the whole corpus and to avoid holding a read cursor open across writes (see
`enqueue`)."""

_ENQUEUE_LOG_EVERY: Final = 10
"""Pages between progress log lines, so a long first-time scan isn't silent."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedFile:
    """A file to process, with its resume cursor.

    `file_id`/`rel_path` are enough to open the file (via the catalog database) and
    process it: title and sentence count are looked up separately, once the file is
    actually opened (see `search.engine._open_file`), so this stays a single-table
    query over the run database's `run_files` alone.
    """

    file_id: int
    rel_path: str
    last_sentence_index: int | None
    chunks_done: int


def enqueue(
    catalog_conn: sqlite3.Connection,
    run_conn: sqlite3.Connection,
    *,
    run_id: int,
    select: "SelectConfig",
    on_progress: "Callable[[], None] | None" = None,
) -> int:
    """Fills `run_files` for a search and returns the number of files added.

    Idempotent: can be re-run to complete the queue of an existing search when new files
    have appeared in the corpus, without touching files already processed.

    Filters on the title require the IMDb datasets to have been imported. Files whose
    identifier remains unresolved are discarded, and their count is logged — otherwise a
    corpus indexed without metadata would produce an empty queue with no explanation.

    When `select.one_subtitle_per_title` is set (the default), a preliminary read-only
    pass (`_prepare_dedup_winners`) picks one file per `(imdb_id, language)` group before
    any pagination starts — see its docstring and ADR-0020.

    Paginates the matching query (against `catalog_conn`) on `sf.file_id` (keyset
    pagination) instead of holding one long-lived `SELECT` cursor open across every
    write: in WAL mode, an open reader pins the checkpoint to the point its snapshot
    began, so a single call iterating a live cursor for the whole corpus while
    interleaving writes would prevent any of its own writes from ever being
    checkpointed. Each page is fully drained, then written (against `run_conn`) in its
    own explicit transaction — never one implicit transaction per row.

    `on_progress`, if given, fires once per row scanned against `select` — in the
    preliminary dedup pass when active *and* in this function's own paginated query
    (restricted, in that case, to the much smaller `dedup_winners` set) — so a caller
    can drive a console progress bar that keeps advancing across either phase, without
    either query's duration depending on it (this function itself has no Rich
    dependency).

    Raises:
        DatabaseError: write failed.
    """
    if select.one_subtitle_per_title:
        _prepare_dedup_winners(catalog_conn, select, on_progress)

    repo = RunFilesRepository(run_conn)
    added = 0
    scanned = 0
    pages = 0
    after_id = 0
    try:
        while True:
            query, params = _matching_page_query(
                select,
                after_id=after_id,
                limit=_ENQUEUE_BATCH_SIZE,
                dedup_active=select.one_subtitle_per_title,
            )
            cursor = catalog_conn.execute(query, params)
            rows = cursor if on_progress is None else _counting(cursor, on_progress)
            batch = [(int(row["file_id"]), str(row["rel_path"])) for row in rows]
            if not batch:
                break
            after_id = batch[-1][0]
            scanned += len(batch)
            run_conn.execute("BEGIN")
            added += repo.enqueue_many(run_id, batch)
            run_conn.execute("COMMIT")
            pages += 1
            if pages % _ENQUEUE_LOG_EVERY == 0:
                _log.info("enqueue: %d file(s) scanned, %d added so far", scanned, added)
            if len(batch) < _ENQUEUE_BATCH_SIZE:
                break
    except sqlite3.Error as exc:
        if run_conn.in_transaction:
            run_conn.execute("ROLLBACK")
        message = f"failed to enqueue files for run {run_id}: {exc}"
        raise DatabaseError(message) from exc

    unresolved_query, unresolved_params = _unresolved_query(select)
    unresolved = int(catalog_conn.execute(unresolved_query, unresolved_params).fetchone()["n"])
    if unresolved:
        _log.warning("%d file(s) excluded from the queue: IMDb id not resolved", unresolved)
    _log.info("%d new file(s) added to run %d's queue", added, run_id)
    return added


def iter_work(
    run_conn: sqlite3.Connection,
    *,
    run_id: int,
    limit: int | None = None,
) -> "Iterator[PlannedFile]":
    """Yields unfinished files, in the plan's deterministic order.

    Generator: the queue can hold hundreds of thousands of entries. A single-table query
    over `run_files` alone — `rel_path` is duplicated there at enqueue time precisely so
    this never needs a join back to the catalog database.

    Args:
        run_conn: run database connection.
        run_id: search concerned.
        limit: stops after this number of files, for a quick trial.

    Yields:
        Files to process, ``ORDER BY rel_path``.
    """
    for count, row in enumerate(RunFilesRepository(run_conn).iter_pending(run_id)):
        if limit is not None and count >= limit:
            break
        yield PlannedFile(
            file_id=row.file_id,
            rel_path=row.rel_path,
            last_sentence_index=row.last_sentence_index,
            chunks_done=row.chunks_done,
        )


def plan_size(run_conn: sqlite3.Connection, run_id: int) -> tuple[int, int]:
    """Returns ``(files done, files planned)`` for displaying progress."""
    progress = RunFilesRepository(run_conn).progress(run_id)
    return progress[FileStatus.DONE], sum(progress.values())


def _select_clauses(select: "SelectConfig") -> tuple[list[str], list[object]]:
    """Shared ``WHERE`` clauses: language and an explicit id list.

    An id in `imdb_ids` matches a file directly (`sf.imdb_id`) or, for a TV episode,
    through its series (`t.parent_imdb_id`) — so listing a series' id selects every one
    of its episodes without the caller having to enumerate them. This relies on the
    `titles` join already present in both callers: `_matching_page_query`'s inner join
    (`t` is the file's own title row) and `_unresolved_query`'s left join, where an
    unresolved file's `t` columns are all `NULL` and only the direct-id branch can still
    match.
    """
    clauses: list[str] = []
    params: list[object] = []
    if select.languages:
        clauses.append(f"sf.language IN ({_placeholders(len(select.languages))})")
        params.extend(select.languages)
    if select.imdb_ids is not None:
        placeholders = _placeholders(len(select.imdb_ids))
        clauses.append(f"(sf.imdb_id IN ({placeholders}) OR t.parent_imdb_id IN ({placeholders}))")
        params.extend(select.imdb_ids)
        params.extend(select.imdb_ids)
    return clauses, params


def _filter_clauses(select: "SelectConfig") -> tuple[list[str], list[object]]:
    """``WHERE`` clauses shared by every query matching `subtitle_files` against `select`.

    Built on top of `_select_clauses` (language, id list): adds the title-level filters
    that also require the `titles` join (type, year range). Shared by
    `_matching_page_query` and `_grouping_query` so the two queries can never disagree on
    which files are in scope — only their column list, pagination, and ordering differ.
    """
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
    return clauses, params


def _matching_page_query(
    select: "SelectConfig", *, after_id: int, limit: int, dedup_active: bool
) -> tuple[str, list[object]]:
    """One page of files whose title resolves and satisfies every filter.

    Keyset-paginated on `sf.file_id` (the table's own `INTEGER PRIMARY KEY`): cheap,
    index-backed, and — unlike an `OFFSET` — its cost doesn't grow with the page number.

    `dedup_active` restricts the page to `dedup_winners`, the temp table
    `_prepare_dedup_winners` must have already staged on the same `catalog_conn` — the
    caller (`enqueue`) is responsible for that ordering.
    """
    clauses, params = _filter_clauses(select)
    clauses.append("sf.file_id > ?")
    params.append(after_id)
    if dedup_active:
        clauses.append("sf.file_id IN (SELECT file_id FROM dedup_winners)")
    where = f" WHERE {' AND '.join(clauses)}"
    query = (
        "SELECT sf.file_id, sf.rel_path FROM subtitle_files sf"
        " JOIN titles t ON t.imdb_id = sf.imdb_id"
        f"{where} ORDER BY sf.file_id LIMIT ?"
    )
    params.append(limit)
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


def _grouping_query(select: "SelectConfig") -> tuple[str, list[object]]:
    """Every candidate matching `select`, ordered for per-`(imdb_id, language)` grouping.

    No pagination: used only by `_prepare_dedup_winners`, which needs every candidate of a
    group in hand before it can pick a winner — a keyset page could otherwise split one
    group across two pages. The resulting *winners* are bounded by title count, not file
    count (see `_prepare_dedup_winners`); the candidate rows themselves are consumed one
    group at a time from a single streamed cursor, never materialized in full.
    """
    clauses, params = _filter_clauses(select)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    query = (
        "SELECT sf.imdb_id, sf.language, sf.file_id, sf.size_bytes, sf.opensubtitles_file_id"
        " FROM subtitle_files sf"
        " JOIN titles t ON t.imdb_id = sf.imdb_id"
        f"{where} ORDER BY sf.imdb_id, sf.language, sf.file_id"
    )
    return query, params


def _group_key(row: sqlite3.Row) -> tuple[int, str]:
    """Groups candidates by `(imdb_id, language)`, matching `_grouping_query`'s ordering."""
    return int(row["imdb_id"]), str(row["language"])


def _prepare_dedup_winners(
    catalog_conn: sqlite3.Connection,
    select: "SelectConfig",
    on_progress: "Callable[[], None] | None" = None,
) -> None:
    """Stages, in a temp table, the winning `file_id` of every `(imdb_id, language)` group.

    A dedicated read-then-write pass, run once before `enqueue`'s own paginated loop
    starts: `_grouping_query` drives a single ordered, streamed cursor with no writes
    interleaved (unlike `enqueue`'s own loop, this reads every matching row once, but
    never holds more than one group in memory at a time — see its docstring), and
    `select_representative` (ADR-0020) picks one winner per group. Those winners — bounded
    by *title* count, an order of magnitude fewer than file count on the real corpus (see
    ADR-0020) — are then staged in batched transactions, exactly like `enqueue`'s own
    write loop.

    `sf.file_id IN (SELECT file_id FROM dedup_winners)` in `_matching_page_query`
    sidesteps SQLite's bound-parameter limit, which inlining the same set as
    `IN (?, ?, ...)` would hit for a corpus-wide search.

    A missing `subtitle_files.size_bytes` (a catalog indexed before this column was
    populated — see `cli/corpus.py`) is treated as `0`, not an error: `corpus index`
    should simply be rerun to get a meaningful ranking, but a stale catalog must still
    produce a deterministic (if degraded) result rather than crash the whole search.

    `on_progress`, if given, fires once per row read from `_grouping_query`'s cursor —
    this is the scan `enqueue`'s own docstring refers to as the dominant cost when
    deduplication is active, since it is unpaginated and reads every matching row.

    Raises:
        DatabaseError: write failed.
    """
    catalog_conn.execute("DROP TABLE IF EXISTS temp.dedup_winners")
    catalog_conn.execute("CREATE TEMP TABLE dedup_winners (file_id INTEGER PRIMARY KEY)")

    query, params = _grouping_query(select)
    cursor = catalog_conn.execute(query, params)
    rows = cursor if on_progress is None else _counting(cursor, on_progress)
    batch: list[tuple[int]] = []
    for _key, group in itertools.groupby(rows, key=_group_key):
        candidates = (
            Candidate(
                file_id=int(row["file_id"]),
                size_bytes=0 if row["size_bytes"] is None else int(row["size_bytes"]),
                opensubtitles_file_id=str(row["opensubtitles_file_id"]),
            )
            for row in group
        )
        winner = select_representative(candidates)
        batch.append((winner.file_id,))
        if len(batch) >= _ENQUEUE_BATCH_SIZE:
            _flush_dedup_winners(catalog_conn, batch)
            batch.clear()
    if batch:
        _flush_dedup_winners(catalog_conn, batch)


def _flush_dedup_winners(catalog_conn: sqlite3.Connection, batch: list[tuple[int]]) -> None:
    """Inserts one batch of dedup winners in its own transaction."""
    catalog_conn.execute("BEGIN")
    try:
        catalog_conn.executemany("INSERT INTO dedup_winners (file_id) VALUES (?)", batch)
    except sqlite3.Error as exc:
        catalog_conn.execute("ROLLBACK")
        message = f"failed to stage subtitle deduplication winners: {exc}"
        raise DatabaseError(message) from exc
    catalog_conn.execute("COMMIT")


def _placeholders(count: int) -> str:
    """``?, ?, ...`` for a dynamically-sized ``IN (...)`` clause."""
    return ", ".join(["?"] * count)


def _counting(
    rows: "Iterator[sqlite3.Row]", on_progress: "Callable[[], None]"
) -> "Iterator[sqlite3.Row]":
    """Wraps a row cursor to fire `on_progress` once per row, before it is consumed."""
    for row in rows:
        on_progress()
        yield row
