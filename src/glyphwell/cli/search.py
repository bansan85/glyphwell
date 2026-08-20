"""Subcommands ``glyphwell search``.

STATUS: commands wired up, processing pending implementation.
"""

from pathlib import Path
from typing import Annotated

import typer

from glyphwell.cli.context import get_context
from glyphwell.search.results import ExportFormat

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
        typer.Option("--concurrency", min=1, help="Chunks analyzed in parallel."),
    ] = None,
) -> None:
    """Launches a search over the indexed corpus.

    An unfinished search sharing the same manifest hash is resumed rather than
    duplicated. The model is checked against Ollama before scanning the corpus.
    """
    settings = get_context(ctx).settings
    _ = (settings, manifest, limit, concurrency)
    raise NotImplementedError


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
