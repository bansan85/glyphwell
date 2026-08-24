"""Search engine: execution loop, concurrency, clean shutdown.

Assembles the other building blocks — planner, XML reader, chunker, pre-filter, LLM
client, checkpoint — and nothing more. All the correctness logic for resuming lives in
`glyphwell.search.checkpoint`; this module merely calls it in the right order.

Two points of attention for the implementation:

* **Concurrency.** Calls to the model run in parallel (`Settings.concurrency`), but SQLite
  writes stay serialized: a single transaction per chunk, never two simultaneous ones on
  the same file.
* **Clean shutdown.** A SIGINT lets the current chunk finish and commit, then moves the
  search to `paused`. A file must never stay `in_progress` with a cursor ahead of the
  results actually recorded.

STATUS: stubs, apart from the value object.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from glyphwell.config import Settings
    from glyphwell.manifest.loader import LoadedManifest
    from glyphwell.ollama.client import LlmClient

__all__ = ["SearchEngine", "SearchOutcome"]


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchOutcome:
    """Summary of an execution or a resume."""

    run_id: int
    files_done: int
    chunks_done: int
    chunks_skipped: int
    """Chunks discarded by the pre-filter, hence without a call to the model."""
    matches: int
    interrupted: bool
    """True if the execution stopped on request: the search is resumable."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchEngine:
    """Runs a search described by a manifest."""

    conn: "sqlite3.Connection"
    client: "LlmClient"
    settings: "Settings"

    def start(self, manifest: "LoadedManifest", *, limit: int | None = None) -> SearchOutcome:
        """Creates a search, builds its queue, then runs it.

        If a search already exists for this manifest hash and is not finished, it is
        resumed instead of being duplicated.

        Args:
            manifest: validated manifest.
            limit: maximum number of files to process, for a trial run.

        Raises:
            SearchError: empty queue, or corpus not indexed.
            OllamaError: model unavailable — checked before scanning the corpus.
        """
        raise NotImplementedError

    def resume(self, run_id: int, *, limit: int | None = None) -> SearchOutcome:
        """Resumes an interrupted search.

        The manifest is re-read from `runs.manifest_snapshot`, not from disk: a resume
        uses exactly the prompt and chunking of the initial run, even if the file has
        since been modified.

        Raises:
            SearchError: unknown or already finished search.
        """
        raise NotImplementedError

    def process_file(self, run_id: int, file_id: int) -> int:
        """Processes a file from its cursor and returns the number of chunks committed.

        The file is re-read from the start and sentences already processed are traversed
        without being emitted: negligible cost compared to a call to the model, and no
        dependency on a byte offset that the slightest content change would invalidate.
        """
        raise NotImplementedError

    def request_stop(self) -> None:
        """Requests a stop at the next chunk boundary.

        Called from the SIGINT handler. Never cuts off an in-flight call: the chunk
        finishes, commits, and the stop happens afterward.
        """
        raise NotImplementedError
