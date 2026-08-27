"""Resume cursor.

The project's most critical module: this is where the promise of "resuming at the
current line" translates into SQLite writes.

Two invariants govern the whole module:

1. **One transaction per chunk.** `commit_chunk` writes the result *and* the cursor's
   progress in the same transaction. A crash can therefore neither lose a result already
   produced, nor advance the cursor beyond what has been recorded.
2. **Idempotence.** Inserting the result is an ``INSERT OR IGNORE`` on
   ``UNIQUE(run_id, file_id, chunk_index)``: replaying a chunk after an interruption does
   not create a duplicate. The duplicate is the normal case, not an error.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from glyphwell.db.repositories import ResultRow, ResultsRepository, RunFilesRepository
from glyphwell.errors import DatabaseError
from glyphwell.types import JsonObject

if TYPE_CHECKING:
    from glyphwell.corpus.chunker import Chunk

__all__ = ["Checkpoint", "commit_chunk", "load_checkpoint", "resume_position"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Checkpoint:
    """Where a file stands in a search.

    Attributes:
        run_id: search concerned.
        file_id: file concerned.
        last_sentence_index: position of the last sentence processed, or `None` if the
            file has not been started yet. **Authoritative** for resuming.
        last_sentence_id: corresponding ``<s id>`` attribute, informational.
        chunks_done: number of chunks already committed, which gives the next
            `Chunk.index`.
    """

    run_id: int
    file_id: int
    last_sentence_index: int | None
    last_sentence_id: str | None
    chunks_done: int

    @property
    def started(self) -> bool:
        """True if at least one chunk has been committed for this file."""
        return self.last_sentence_index is not None


def load_checkpoint(
    run_conn: sqlite3.Connection, *, run_id: int, file_id: int
) -> Checkpoint | None:
    """Reads a file's cursor, or `None` if it is not in this search's queue."""
    row = RunFilesRepository(run_conn).get(run_id, file_id)
    if row is None:
        return None
    return Checkpoint(
        run_id=run_id,
        file_id=file_id,
        last_sentence_index=row.last_sentence_index,
        last_sentence_id=row.last_sentence_id,
        chunks_done=row.chunks_done,
    )


def resume_position(checkpoint: Checkpoint | None, *, overlap: int) -> tuple[int, int]:
    """Computes where to resume reading a file.

    Args:
        checkpoint: current cursor, or `None` for a fresh file.
        overlap: manifest overlap.

    Returns:
        The pair ``(start_index, start_chunk_index)``: first sentence to emit, and the
        number to give the first chunk produced. The two values must stay consistent,
        otherwise `chunk_index` would stop designating the same sentence range as on the
        first pass and the uniqueness constraint would lose its meaning.

        The last committed chunk is ``chunks_done - 1``, whose last covered index is
        `last_sentence_index`; the next chunk must start `overlap` sentences before that
        (clamped to 0), and ``chunks_done`` is directly the index to give it. Chunk width
        plays no part in this: `iter_chunks` derives it from the token budget, not from a
        fixed stride, so only `overlap` matters here.
    """
    if checkpoint is None or not checkpoint.started:
        return 0, 0
    assert checkpoint.last_sentence_index is not None  # `started` guarantees this
    start_index = max(checkpoint.last_sentence_index + 1 - overlap, 0)
    return start_index, checkpoint.chunks_done


def commit_chunk(
    run_conn: sqlite3.Connection,
    *,
    run_id: int,
    file_id: int,
    chunk: "Chunk",
    matched: bool,
    payload: JsonObject | None,
    model: str,
    latency_ms: int | None,
) -> bool:
    """Records a chunk's result and advances the cursor, in one transaction.

    The cursor write is unconditional, regardless of whether the result row was newly
    inserted: given a correctly computed `resume_position` and chunks committed strictly
    in order, `commit_chunk` is only ever called with `chunk.index` equal to the file's
    current `chunks_done` — replaying it writes the exact same values again, a safe
    no-op. The ``INSERT OR IGNORE`` / always-advance combination is defense in depth, not
    a routine path.

    Returns:
        True if a result was inserted, false if the chunk was already recorded — which
        normally happens on resume and is not an error. In both cases the cursor is
        advanced.

    Raises:
        DatabaseError: write failed. The transaction is then rolled back: the cursor stays
            at the last chunk actually recorded.
    """
    row = ResultRow(
        result_id=0,  # disregarded by `insert_ignore`, autoincrement primary key
        run_id=run_id,
        file_id=file_id,
        chunk_index=chunk.index,
        first_sentence_index=chunk.first.index,
        last_sentence_index=chunk.last.index,
        matched=matched,
        payload=payload,
        model=model,
        latency_ms=latency_ms,
    )
    try:
        run_conn.execute("BEGIN IMMEDIATE")
        inserted = ResultsRepository(run_conn).insert_ignore(row)
        RunFilesRepository(run_conn).advance(
            run_id,
            file_id,
            last_sentence_index=chunk.last.index,
            last_sentence_id=chunk.last.id,
            chunks_done=chunk.index + 1,
        )
        run_conn.execute("COMMIT")
    except sqlite3.Error as exc:
        run_conn.execute("ROLLBACK")
        message = f"failed to commit chunk {chunk.index + 1} of file {file_id} (run {run_id}): {exc}"
        raise DatabaseError(message) from exc
    return inserted
