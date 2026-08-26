"""Search engine: execution loop, concurrency, clean shutdown.

Assembles the other building blocks — planner, XML reader, chunker, pre-filter, LLM
client, checkpoint — and nothing more. All the correctness logic for resuming lives in
`glyphwell.search.checkpoint`; this module merely calls it in the right order.

Two points of attention for the implementation:

* **Concurrency.** Calls to the model run in parallel (`Settings.concurrency`), but SQLite
  writes stay serialized: a single transaction per chunk, never two simultaneous ones on
  the same file. `glyphwell.db.connection` opens the connection without
  ``check_same_thread=False``, so it can only ever be touched from the thread that owns
  it — every DB- or corpus-reading operation therefore happens on that single thread.
  Worker threads exist only to run `LlmClient.complete`, a pure I/O call that touches
  neither the connection nor a shared archive handle: concurrency is across *files*, not
  within one file's own chunk sequence, which stays strictly sequential.
* **Clean shutdown.** A SIGINT lets the current chunk finish and commit, then moves the
  search to `paused`. A file must never stay `in_progress` with a cursor ahead of the
  results actually recorded.
"""

import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING

import yaml

from glyphwell.corpus.archive import CorpusArchive
from glyphwell.corpus.chunker import iter_chunks
from glyphwell.corpus.reader import iter_sentences
from glyphwell.db.repositories import (
    CorpusDownloadsRepository,
    RunFilesRepository,
    RunRow,
    RunsRepository,
    RunStatus,
    SubtitleFilesRepository,
)
from glyphwell.errors import CorpusError, OllamaError, SearchError
from glyphwell.logging import get_logger
from glyphwell.manifest.model import SearchManifest
from glyphwell.manifest.prefilter import Prefilter
from glyphwell.metadata.resolver import SqliteTitleProvider
from glyphwell.ollama.prompts import render, render_context
from glyphwell.search import planner
from glyphwell.search.checkpoint import commit_chunk, load_checkpoint, resume_position
from glyphwell.search.results import validate_output
from glyphwell.types import ImdbId

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Iterator, Mapping

    from glyphwell.config import Settings
    from glyphwell.corpus.chunker import Chunk
    from glyphwell.manifest.loader import LoadedManifest
    from glyphwell.manifest.model import OutputConfig
    from glyphwell.metadata.resolver import Title
    from glyphwell.ollama.client import Completion, LlmClient
    from glyphwell.types import JsonValue

__all__ = ["SearchEngine", "SearchOutcome"]

_log = get_logger(__name__)


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
class _FileState:
    """A file's live reading state: its open stream and chunk generator.

    Not stored anywhere: it only exists for the duration of one file's processing,
    whether driven by `SearchEngine.process_file` or the multi-file loop.
    """

    file_id: int
    rel_path: str
    stream: IO[bytes]
    chunks: "Iterator[Chunk]"
    title: "Title | None"
    imdb_id: ImdbId


@dataclass(slots=True)
class _Counters:
    """Mutable running totals, accumulated while a search's queue is processed."""

    files_done: int = 0
    chunks_done: int = 0
    chunks_skipped: int = 0
    matches: int = 0


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchEngine:
    """Runs a search described by a manifest.

    Two databases, two connections: `catalog_conn` (titles, subtitle_files,
    corpus_downloads — immutable, shared across every search) and `run_conn` (runs,
    run_files, results — mutable, one file per search). See ADR-0018.
    """

    catalog_conn: "sqlite3.Connection"
    run_conn: "sqlite3.Connection"
    client: "LlmClient"
    settings: "Settings"
    _stop_event: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False, compare=False
    )

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
        _log.info("checking model %r is available", manifest.model)
        self.client.ensure_model(manifest.model)
        runs = RunsRepository(self.run_conn)
        existing = runs.find_by_hash(manifest.hash)
        if existing and existing[0].status is not RunStatus.DONE:
            _log.info("manifest matches existing run %d, resuming it", existing[0].run_id)
            return self.resume(existing[0].run_id, limit=limit)

        run_id = runs.create(
            manifest_path=str(manifest.path),
            manifest_hash=manifest.hash,
            manifest_snapshot=manifest.source,
            model=manifest.model,
        )
        _log.info("created run %d for manifest %s", run_id, manifest.path)
        return self._run(run_id, manifest.manifest, limit=limit, rebuild_queue=True)

    def resume(self, run_id: int, *, limit: int | None = None) -> SearchOutcome:
        """Resumes an interrupted search.

        The manifest is re-read from `runs.manifest_snapshot`, not from disk: a resume
        uses exactly the prompt and chunking of the initial run, even if the file has
        since been modified.

        Raises:
            SearchError: unknown or already finished search.
        """
        row = _require_run(self.run_conn, run_id)
        if row.status is RunStatus.DONE:
            message = f"search {run_id} is already finished"
            raise SearchError(message)

        manifest = _manifest_from_run(self.run_conn, run_id)
        _log.info("resuming run %d (%s)", run_id, manifest.name)
        self.client.ensure_model(manifest.model)
        return self._run(run_id, manifest, limit=limit, rebuild_queue=False)

    def process_file(self, run_id: int, file_id: int) -> int:
        """Processes a file from its cursor and returns the number of chunks committed.

        The file is re-read from the start and sentences already processed are traversed
        without being emitted: negligible cost compared to a call to the model, and no
        dependency on a byte offset that the slightest content change would invalidate.
        """
        _require_run(self.run_conn, run_id)
        manifest = _manifest_from_run(self.run_conn, run_id)
        prefilter = Prefilter.compile(manifest.prefilter)
        titles = SqliteTitleProvider(self.catalog_conn)
        run_files = RunFilesRepository(self.run_conn)
        counters = _Counters()
        archives: dict[tuple[str, str], CorpusArchive] = {}

        try:
            state = _open_file(
                self.catalog_conn,
                self.run_conn,
                archives,
                self.settings,
                run_id,
                file_id,
                manifest,
                titles,
            )
            if state is None:
                return 0
            chunk = _next_evaluable_chunk(
                self.run_conn,
                run_id=run_id,
                file_id=file_id,
                model=manifest.model,
                state=state,
                prefilter=prefilter,
                counters=counters,
            )
            while chunk is not None:
                try:
                    completion = _complete_chunk(self.client, manifest, state, chunk)
                except OllamaError as exc:
                    run_files.mark_error(run_id, file_id, str(exc))
                    _log.warning(
                        "chunk %d of file %d (%s) failed, file marked error: %s",
                        chunk.index,
                        file_id,
                        state.rel_path,
                        exc,
                    )
                    return counters.chunks_done + counters.chunks_skipped
                _commit_completion(
                    self.run_conn,
                    run_id=run_id,
                    file_id=file_id,
                    chunk=chunk,
                    manifest=manifest,
                    completion=completion,
                    counters=counters,
                )
                chunk = _next_evaluable_chunk(
                    self.run_conn,
                    run_id=run_id,
                    file_id=file_id,
                    model=manifest.model,
                    state=state,
                    prefilter=prefilter,
                    counters=counters,
                )
            run_files.mark_done(run_id, file_id)
            _log.info("file done: %s", state.rel_path)
        finally:
            for archive in archives.values():
                archive.close()
        return counters.chunks_done + counters.chunks_skipped

    def request_stop(self) -> None:
        """Requests a stop at the next chunk boundary.

        Called from the SIGINT handler. Never cuts off an in-flight call: the chunk
        finishes, commits, and the stop happens afterward.
        """
        self._stop_event.set()

    def _run(
        self,
        run_id: int,
        manifest: SearchManifest,
        *,
        limit: int | None,
        rebuild_queue: bool,
    ) -> SearchOutcome:
        """Shared driving logic for `start` and `resume`: enqueue if needed, then process.

        `rebuild_queue` is false on a resume: the queue was already fully populated by
        the run's original `start()`, and re-running `planner.enqueue`'s corpus-wide join
        on every resume would pay its full cost again for zero new rows. `start()` always
        passes true, since a freshly created run has no queue yet.
        """
        runs = RunsRepository(self.run_conn)
        runs.set_status(run_id, RunStatus.RUNNING)
        if rebuild_queue:
            _log.info("building the work queue (select filters)")
            planner.enqueue(self.catalog_conn, self.run_conn, run_id=run_id, select=manifest.select)

        done, planned = planner.plan_size(self.run_conn, run_id)
        if planned == 0:
            runs.set_status(run_id, RunStatus.FAILED)
            message = "no file in the corpus matches this manifest's select filters"
            raise SearchError(message)
        _log.info(
            "run %d: %d/%d file(s) already done, %d remaining",
            run_id,
            done,
            planned,
            planned - done,
        )

        prefilter = Prefilter.compile(manifest.prefilter)
        outcome = self._process_queue(run_id, manifest, prefilter, limit=limit)
        runs.set_status(run_id, RunStatus.PAUSED if outcome.interrupted else RunStatus.DONE)
        _log.info(
            "run %d %s: %d file(s), %d chunk(s) done, %d skipped, %d match(es)",
            run_id,
            "paused" if outcome.interrupted else "done",
            outcome.files_done,
            outcome.chunks_done,
            outcome.chunks_skipped,
            outcome.matches,
        )
        return outcome

    def _process_queue(
        self,
        run_id: int,
        manifest: SearchManifest,
        prefilter: Prefilter,
        *,
        limit: int | None,
    ) -> SearchOutcome:
        """Processes every pending file, up to `Settings.concurrency` in flight at once."""
        titles = SqliteTitleProvider(self.catalog_conn)
        run_files = RunFilesRepository(self.run_conn)
        archives: dict[tuple[str, str], CorpusArchive] = {}
        counters = _Counters()
        concurrency = max(1, self.settings.concurrency)
        pending = planner.iter_work(self.run_conn, run_id=run_id, limit=limit)

        try:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                active: dict[Future[Completion], tuple[int, _FileState, Chunk]] = {}

                def _admit() -> bool:
                    if self._stop_event.is_set():
                        return False
                    for planned in pending:
                        state = _open_file(
                            self.catalog_conn,
                            self.run_conn,
                            archives,
                            self.settings,
                            run_id,
                            planned.file_id,
                            manifest,
                            titles,
                        )
                        if state is None:
                            continue
                        chunk = _next_evaluable_chunk(
                            self.run_conn,
                            run_id=run_id,
                            file_id=planned.file_id,
                            model=manifest.model,
                            state=state,
                            prefilter=prefilter,
                            counters=counters,
                        )
                        if chunk is None:
                            run_files.mark_done(run_id, planned.file_id)
                            state.stream.close()
                            counters.files_done += 1
                            _log.info("file done: %s", state.rel_path)
                            continue
                        future = executor.submit(
                            _complete_chunk, self.client, manifest, state, chunk
                        )
                        active[future] = (planned.file_id, state, chunk)
                        return True
                    return False

                while len(active) < concurrency and _admit():
                    pass

                while active:
                    finished, _still_running = wait(active, return_when=FIRST_COMPLETED)
                    for future in finished:
                        file_id, state, chunk = active.pop(future)
                        try:
                            completion = future.result()
                        except OllamaError as exc:
                            run_files.mark_error(run_id, file_id, str(exc))
                            _log.warning(
                                "chunk %d of file %d (%s) failed, file marked error: %s",
                                chunk.index,
                                file_id,
                                state.rel_path,
                                exc,
                            )
                            state.stream.close()
                            counters.files_done += 1
                            continue

                        _commit_completion(
                            self.run_conn,
                            run_id=run_id,
                            file_id=file_id,
                            chunk=chunk,
                            manifest=manifest,
                            completion=completion,
                            counters=counters,
                        )

                        if self._stop_event.is_set():
                            state.stream.close()
                            continue

                        next_chunk = _next_evaluable_chunk(
                            self.run_conn,
                            run_id=run_id,
                            file_id=file_id,
                            model=manifest.model,
                            state=state,
                            prefilter=prefilter,
                            counters=counters,
                        )
                        if next_chunk is None:
                            run_files.mark_done(run_id, file_id)
                            state.stream.close()
                            counters.files_done += 1
                            _log.info("file done: %s", state.rel_path)
                        else:
                            next_future = executor.submit(
                                _complete_chunk, self.client, manifest, state, next_chunk
                            )
                            active[next_future] = (file_id, state, next_chunk)

                    while len(active) < concurrency and _admit():
                        pass
        finally:
            for archive in archives.values():
                archive.close()

        return SearchOutcome(
            run_id=run_id,
            files_done=counters.files_done,
            chunks_done=counters.chunks_done,
            chunks_skipped=counters.chunks_skipped,
            matches=counters.matches,
            interrupted=self._stop_event.is_set(),
        )


def _require_run(run_conn: "sqlite3.Connection", run_id: int) -> RunRow:
    """Fetches a run's row, or raises `SearchError` if it doesn't exist."""
    row = RunsRepository(run_conn).get(run_id)
    if row is None:
        message = f"unknown search: {run_id}"
        raise SearchError(message)
    return row


def _manifest_from_run(run_conn: "sqlite3.Connection", run_id: int) -> SearchManifest:
    """Re-parses a run's manifest from its archived snapshot, never from disk."""
    snapshot = RunsRepository(run_conn).get_manifest_snapshot(run_id)
    if snapshot is None:
        message = f"unknown search: {run_id}"
        raise SearchError(message)
    raw: object = yaml.safe_load(snapshot)
    return SearchManifest.model_validate(raw)


def _get_archive(
    archives: dict[tuple[str, str], CorpusArchive],
    catalog_conn: "sqlite3.Connection",
    settings: "Settings",
    opus_version: str,
    language: str,
) -> CorpusArchive | None:
    """Returns the (cached) archive backing a file's `(opus_version, language)`.

    One `CorpusArchive` per distinct pair for the lifetime of a run — opening one reloads
    the whole central directory, far too costly to redo per file.
    """
    key = (opus_version, language)
    cached = archives.get(key)
    if cached is not None:
        return cached
    download = CorpusDownloadsRepository(catalog_conn).get(
        opus_corpus=settings.opus_corpus, opus_version=opus_version, language=language
    )
    if download is None or download.archive_path is None:
        return None
    archive = CorpusArchive(Path(download.archive_path))
    archives[key] = archive
    return archive


def _open_file(
    catalog_conn: "sqlite3.Connection",
    run_conn: "sqlite3.Connection",
    archives: dict[tuple[str, str], CorpusArchive],
    settings: "Settings",
    run_id: int,
    file_id: int,
    manifest: SearchManifest,
    titles: SqliteTitleProvider,
) -> _FileState | None:
    """Opens a file's member stream and positions its chunk generator at its cursor.

    Returns `None` (logging why) when the file cannot be processed at all: vanished from
    the catalog, no downloaded archive for its `(opus_version, language)`, or an unreadable
    member — each of these is a per-file problem, not a reason to abort the whole search.
    """
    file_row = SubtitleFilesRepository(catalog_conn).get(file_id)
    if file_row is None:
        _log.warning("file %d vanished from the catalog, skipping", file_id)
        return None

    archive = _get_archive(
        archives, catalog_conn, settings, file_row.opus_version, file_row.language
    )
    if archive is None:
        _log.warning(
            "no downloaded archive for %s/%s: skipping file %d",
            file_row.opus_version,
            file_row.language,
            file_id,
        )
        return None

    checkpoint = load_checkpoint(run_conn, run_id=run_id, file_id=file_id)
    start_index, start_chunk_index = resume_position(
        checkpoint, size=manifest.chunk.size, overlap=manifest.chunk.overlap
    )

    try:
        stream = archive.open_member(file_row.rel_path)
    except CorpusError as exc:
        RunFilesRepository(run_conn).mark_error(run_id, file_id, str(exc))
        _log.warning("could not open %s: %s", file_row.rel_path, exc)
        return None

    sentences = iter_sentences(stream, start_index=start_index)
    chunks = iter_chunks(
        sentences,
        size=manifest.chunk.size,
        overlap=manifest.chunk.overlap,
        start_chunk_index=start_chunk_index,
    )
    title = titles.resolve(file_row.imdb_id)
    _log.debug(
        "opening %s (file %d): resuming at sentence %d, chunk %d",
        file_row.rel_path,
        file_id,
        start_index,
        start_chunk_index,
    )
    return _FileState(
        file_id=file_id,
        rel_path=file_row.rel_path,
        stream=stream,
        chunks=chunks,
        title=title,
        imdb_id=file_row.imdb_id,
    )


def _next_evaluable_chunk(
    run_conn: "sqlite3.Connection",
    *,
    run_id: int,
    file_id: int,
    model: str,
    state: _FileState,
    prefilter: Prefilter,
    counters: _Counters,
) -> "Chunk | None":
    """Pulls chunks until one needs a model call, committing prefiltered ones inline.

    A prefiltered-out chunk still gets a `results` row (``matched=False, payload=None``):
    `commit_chunk` is the only way to advance the cursor, and `results` stays a gapless
    ledger of every `chunk_index` for the file.
    """
    for chunk in state.chunks:
        if prefilter.enabled and not prefilter.keeps(chunk.render(with_ids=False)):
            commit_chunk(
                run_conn,
                run_id=run_id,
                file_id=file_id,
                chunk=chunk,
                matched=False,
                payload=None,
                model=model,
                latency_ms=None,
            )
            counters.chunks_skipped += 1
            _log.debug("chunk %d of file %d: skipped by the pre-filter", chunk.index, file_id)
            continue
        return chunk
    return None


def _effective_schema(output: "OutputConfig") -> "Mapping[str, JsonValue] | None":
    """What to ask Ollama to constrain generation to, derived from `output.format`.

    This policy lives here, not in `glyphwell.ollama.client`, which stays decoupled from
    `glyphwell.manifest`.
    """
    if output.format == "text":
        return None
    if output.json_schema is not None:
        return output.json_schema
    return {"type": "object"}


def _complete_chunk(
    client: "LlmClient", manifest: SearchManifest, state: _FileState, chunk: "Chunk"
) -> "Completion":
    """Renders a chunk's prompt and submits it to the model.

    A free function (not a method) so it can be handed to `ThreadPoolExecutor.submit`
    without capturing `self`.
    """
    _log.debug("chunk %d of file %d", chunk.index, state.file_id)
    context = render_context(chunk=chunk, title=state.title, imdb_id=state.imdb_id)
    system = None if manifest.prompt.system is None else render(manifest.prompt.system, context)
    user = render(manifest.prompt.user, context)
    return client.complete(
        model=manifest.model,
        user=user,
        system=system,
        options=manifest.options,
        json_schema=_effective_schema(manifest.output),
    )


def _commit_completion(
    run_conn: "sqlite3.Connection",
    *,
    run_id: int,
    file_id: int,
    chunk: "Chunk",
    manifest: SearchManifest,
    completion: "Completion",
    counters: _Counters,
) -> None:
    """Validates a model response and commits it, updating the running counters."""
    lines_by_id = {sentence.id: sentence.text for sentence in chunk.sentences}
    validated = validate_output(
        completion.text,
        output=manifest.output,
        match_when=manifest.match_when,
        lines_by_id=lines_by_id,
    )
    commit_chunk(
        run_conn,
        run_id=run_id,
        file_id=file_id,
        chunk=chunk,
        matched=validated.matched,
        payload=validated.payload,
        model=completion.model,
        latency_ms=completion.latency_ms,
    )
    counters.chunks_done += 1
    if validated.matched:
        counters.matches += 1
        _log.debug(
            "chunk %d of file %d: matched (%dms): %s",
            chunk.index,
            file_id,
            completion.latency_ms,
            validated.payload,
        )
    else:
        _log.debug(
            "chunk %d of file %d: no match (%dms)",
            chunk.index,
            file_id,
            completion.latency_ms,
        )
