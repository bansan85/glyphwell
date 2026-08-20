"""Building a search's work queue.

The planner translates the manifest's ``select`` filters into a set of files, then
materializes that set into `run_files`. Materializing the queue rather than recomputing it
every round has two virtues: progress is measurable, and a resume picks up exactly the
same list even if the corpus has grown in the meantime.

**Order is an invariant, not a detail.** Traversal is always ``ORDER BY
subtitle_files.rel_path``. Without this fixed order, `chunk_index` would not designate the
same sentence range from one run to the next, and the uniqueness constraint on `results`
would stop guaranteeing idempotence.

STATUS: stubs, apart from the value object.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from glyphwell.manifest.model import SelectConfig

__all__ = ["PlannedFile", "enqueue", "iter_work", "plan_size"]


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
    raise NotImplementedError


def iter_work(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    limit: int | None = None,
) -> "Iterator[PlannedFile]":
    """Yields unfinished files, in the plan's deterministic order.

    Generator: the queue can hold hundreds of thousands of entries.

    Args:
        conn: database connection.
        run_id: search concerned.
        limit: stops after this number of files, for a quick trial.

    Yields:
        Files to process, ``ORDER BY rel_path``.
    """
    raise NotImplementedError


def plan_size(conn: sqlite3.Connection, run_id: int) -> tuple[int, int]:
    """Returns ``(files done, files planned)`` for displaying progress."""
    raise NotImplementedError
