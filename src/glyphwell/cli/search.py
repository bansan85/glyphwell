"""Subcommands ``glyphwell search``.

STATUS: ``run`` (including ``--dry-run``) is operational; ``resume``, ``status`` and
``export`` remain pending.
"""

import json
import signal
from pathlib import Path
from types import FrameType
from typing import TYPE_CHECKING, Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from glyphwell.cli.context import get_context
from glyphwell.console import console
from glyphwell.corpus.archive import CorpusArchive
from glyphwell.corpus.chunker import iter_chunks
from glyphwell.corpus.layout import iter_corpus
from glyphwell.corpus.reader import iter_sentences
from glyphwell.db import connect, ensure_current
from glyphwell.db.repositories import CorpusDownloadsRepository
from glyphwell.errors import SearchError
from glyphwell.manifest import load
from glyphwell.metadata.resolver import SqliteTitleProvider
from glyphwell.ollama.client import OllamaClient
from glyphwell.ollama.prompts import render, render_context
from glyphwell.search.engine import SearchEngine, SearchOutcome
from glyphwell.search.results import ExportFormat

if TYPE_CHECKING:
    from glyphwell.config import Settings
    from glyphwell.corpus.layout import CorpusEntry
    from glyphwell.manifest.loader import LoadedManifest
    from glyphwell.manifest.model import SelectConfig
    from glyphwell.metadata.resolver import Title

__all__ = ["app"]

app = typer.Typer(
    help="Launching, resuming, tracking and exporting searches.",
    no_args_is_help=True,
)


@app.command("run")
def run(
    ctx: typer.Context,
    manifest: Annotated[
        Path,
        typer.Argument(help="YAML manifest describing the search.", exists=True, dir_okay=False),
    ],
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum number of files, for a trial run."),
    ] = None,
    concurrency: Annotated[
        int | None,
        typer.Option("--concurrency", min=1, max=64, help="Chunks analyzed in parallel."),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help=(
                "Renders one example prompt and its Ollama parameters, without touching"
                " the database or calling Ollama."
            ),
        ),
    ] = False,
) -> None:
    """Launches a search over the indexed corpus.

    An unfinished search sharing the same manifest hash is resumed rather than
    duplicated. The model is checked against Ollama before scanning the corpus.

    ``--dry-run`` skips all of that: it picks one real file matching the manifest's
    ``select`` filters from the already-downloaded archive, renders its first chunk's
    prompt exactly as it would be sent, and prints it — nothing is written to the
    database and Ollama is never called.
    """
    settings = get_context(ctx).settings
    loaded = load(manifest)

    if dry_run:
        _run_dry(settings, loaded)
        return

    overrides = {"concurrency": concurrency}
    effective = settings if concurrency is None else settings.model_copy(update=overrides)
    client = OllamaClient(host=effective.ollama_host, timeout=effective.ollama_timeout)
    with connect(effective.database_path) as conn:
        ensure_current(conn)
        engine = SearchEngine(conn=conn, client=client, settings=effective)
        _install_sigint_handler(engine)
        outcome = engine.start(loaded, limit=limit)
    _report_outcome(outcome)


def _install_sigint_handler(engine: SearchEngine) -> None:
    """Makes a first Ctrl+C request a clean stop; a second one aborts as usual."""
    previous = signal.getsignal(signal.SIGINT)

    def _handler(_signum: int, _frame: FrameType | None) -> None:
        console.print(
            "\n[yellow]Stopping…[/yellow] finishing the current chunk(s), then pausing."
            " Press Ctrl+C again to abort immediately."
        )
        engine.request_stop()
        signal.signal(signal.SIGINT, previous)

    signal.signal(signal.SIGINT, _handler)


def _report_outcome(outcome: SearchOutcome) -> None:
    """Summarizes what a run (or resume) accomplished."""
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Run", str(outcome.run_id))
    table.add_row("Files done", str(outcome.files_done))
    table.add_row("Chunks done", str(outcome.chunks_done))
    table.add_row("Chunks skipped", str(outcome.chunks_skipped))
    table.add_row("Matches", str(outcome.matches))
    if outcome.interrupted:
        table.add_row(
            "Status",
            f"[yellow]paused[/yellow] — resume with `glyphwell search resume {outcome.run_id}`",
        )
    else:
        table.add_row("Status", "[green]done[/green]")
    console.print(table)


def _run_dry(settings: "Settings", loaded: "LoadedManifest") -> None:
    """Renders one real example prompt, without writing anything or calling Ollama."""
    manifest = loaded.manifest
    with connect(settings.database_path) as conn:
        ensure_current(conn)
        download = CorpusDownloadsRepository(conn).get(
            opus_corpus=settings.opus_corpus,
            opus_version=settings.opus_version,
            language=settings.opus_language,
        )
        if download is None or download.archive_path is None:
            message = "no downloaded corpus archive: run `glyphwell corpus fetch` first"
            raise SearchError(message)

        titles = SqliteTitleProvider(conn)
        with CorpusArchive(Path(download.archive_path)) as archive:
            found = _first_match(archive, manifest.select, titles)
            if found is None:
                message = "no file in the corpus matches this manifest's select filters"
                raise SearchError(message)
            entry, title = found
            with archive.open_member(entry.rel_path) as stream:
                sentences = iter_sentences(stream)
                chunks = iter_chunks(
                    sentences, size=manifest.chunk.size, overlap=manifest.chunk.overlap
                )
                chunk = next(chunks, None)

    if chunk is None:
        message = f"{entry.rel_path} has no sentences to chunk"
        raise SearchError(message)

    context = render_context(chunk=chunk, title=title, imdb_id=entry.imdb_id)
    system_text = (
        None if manifest.prompt.system is None else render(manifest.prompt.system, context)
    )
    user_text = render(manifest.prompt.user, context)
    _print_dry_run(
        settings=settings,
        loaded=loaded,
        entry=entry,
        title=title,
        system_text=system_text,
        user_text=user_text,
    )


def _first_match(
    archive: CorpusArchive,
    select: "SelectConfig",
    titles: SqliteTitleProvider,
) -> "tuple[CorpusEntry, Title | None] | None":
    """First archive entry matching `select`, in encounter order.

    Not the planner's ``ORDER BY rel_path``: sorting the whole entry stream just to
    preview one file would be wasteful at corpus scale. An id that doesn't resolve to a
    title is excluded, mirroring `glyphwell.search.planner.enqueue`'s own policy.
    """
    for entry in iter_corpus(archive):
        title = titles.resolve(entry.imdb_id)
        if _matches_select(entry, title, select):
            return entry, title
    return None


def _matches_select(entry: "CorpusEntry", title: "Title | None", select: "SelectConfig") -> bool:
    """Whether a corpus entry satisfies a manifest's `select` filters."""
    if select.languages and entry.language not in select.languages:
        return False
    if select.imdb_ids is not None and entry.imdb_id not in select.imdb_ids:
        return False
    if title is None:
        return False
    if select.title_types and title.title_type not in select.title_types:
        return False
    year_min = select.years.min
    if year_min is not None and (title.start_year is None or title.start_year < year_min):
        return False
    year_max = select.years.max
    return not (year_max is not None and (title.start_year is None or title.start_year > year_max))


def _print_dry_run(
    *,
    settings: "Settings",
    loaded: "LoadedManifest",
    entry: "CorpusEntry",
    title: "Title | None",
    system_text: str | None,
    user_text: str,
) -> None:
    """Displays the manifest's parameters, then the fully rendered prompt."""
    manifest = loaded.manifest
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Manifest", f"{loaded.name} ({loaded.hash[:12]})")
    table.add_row("File", entry.rel_path)
    table.add_row("Title", title.display_name() if title is not None else entry.imdb_id)
    table.add_row("Model", manifest.model)
    table.add_row("Options", json.dumps(manifest.options) if manifest.options else "{}")
    table.add_row("Output format", manifest.output.format)
    table.add_row("Output schema", "yes" if manifest.output.json_schema is not None else "no")
    table.add_row("Ollama host", settings.ollama_host)
    table.add_row("Ollama timeout", f"{settings.ollama_timeout}s")
    console.print(table)

    if system_text is not None:
        console.print(Panel(system_text, title="system prompt", border_style="blue"))
    console.print(Panel(user_text, title="user prompt", border_style="green"))
    if manifest.output.json_schema is not None:
        console.print(
            Panel(json.dumps(manifest.output.json_schema, indent=2), title="output.schema")
        )


@app.command("resume")
def resume(
    ctx: typer.Context,
    run_id: Annotated[int, typer.Argument(help="Identifier of the search to resume.")],
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Maximum number of files to process."),
    ] = None,
) -> None:
    """Resumes an interrupted search, at the row where it stopped.

    The manifest is re-read from the snapshot archived at launch, not from disk:
    the resume uses exactly the original prompt and chunking.
    """
    settings = get_context(ctx).settings
    _ = (settings, run_id, limit)
    raise NotImplementedError


@app.command("status")
def status(
    ctx: typer.Context,
    run_id: Annotated[
        int | None,
        typer.Argument(help="Search to detail. Without an argument: lists everything."),
    ] = None,
) -> None:
    """Displays the progress of searches."""
    settings = get_context(ctx).settings
    _ = (settings, run_id)
    raise NotImplementedError


@app.command("export")
def export(
    ctx: typer.Context,
    run_id: Annotated[int, typer.Argument(help="Search to export.")],
    export_format: Annotated[
        ExportFormat,
        typer.Option("--format", "-f", help="Output format."),
    ] = ExportFormat.JSONL,
    dest: Annotated[
        Path | None,
        typer.Option("--dest", "-o", help="Output file. Default: <data-dir>/exports/"),
    ] = None,
    matched_only: Annotated[
        bool,
        typer.Option("--matched-only/--all", help="Only export matches."),
    ] = True,
) -> None:
    """Exports the results of a search.

    Titles are resolved at export time: re-importing the IMDb datasets improves
    subsequent exports without touching results already recorded.
    """
    settings = get_context(ctx).settings
    _ = (settings, run_id, export_format, dest, matched_only)
    raise NotImplementedError
