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

STATUS: stubs, apart from the value object.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

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


def load_checkpoint(conn: sqlite3.Connection, *, run_id: int, file_id: int) -> Checkpoint | None:
    """Reads a file's cursor, or `None` if it is not in this search's queue."""
    raise NotImplementedError


def resume_position(checkpoint: Checkpoint | None, *, size: int, overlap: int) -> tuple[int, int]:
    """Computes where to resume reading a file.

    Args:
        checkpoint: current cursor, or `None` for a fresh file.
        size: manifest chunk size.
        overlap: manifest overlap.

    Returns:
        The pair ``(start_index, start_chunk_index)``: first sentence to emit, and the
        number to give the first chunk produced. The two values must stay consistent,
        otherwise `chunk_index` would stop designating the same sentence range as on the
        first pass and the uniqueness constraint would lose its meaning.
    """
    raise NotImplementedError


def commit_chunk(
    conn: sqlite3.Connection,
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

    Returns:
        True if a result was inserted, false if the chunk was already recorded — which
        normally happens on resume and is not an error. In both cases the cursor is
        advanced.

    Raises:
        DatabaseError: write failed. The transaction is then rolled back: the cursor stays
            at the last chunk actually recorded.
    """
    raise NotImplementedError
