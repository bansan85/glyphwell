"""Subcommands ``glyphwell metadata``."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from glyphwell.cli.context import get_context
from glyphwell.console import console
from glyphwell.db import connect, ensure_current
from glyphwell.db.repositories import ImportRow, ImportSource, ImportsRepository
from glyphwell.metadata.imdb_datasets import (
    ImdbDataset,
    ProgressCallback,
    download,
    import_basics,
    import_episodes,
    locate_dataset,
)

__all__ = ["app"]

app = typer.Typer(
    help="Download and import of title metadata from the IMDb datasets.",
    no_args_is_help=True,
)


@app.command("fetch-imdb")
def fetch_imdb(
    ctx: typer.Context,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-downloads even if the files are already present."),
    ] = False,
) -> None:
    """Downloads `title.basics.tsv.gz` and `title.episode.tsv.gz`.

    IMDb non-commercial datasets: no API key, republished daily.
    """
    settings = get_context(ctx).settings
    settings.ensure_directories()
    for dataset in ImdbDataset:
        console.print(f"Downloading [bold]{dataset.url}[/bold]…")
        path = download(dataset, dest_dir=settings.downloads_dir, force=force)
        console.print(f"  -> {path}")


@app.command("import-imdb")
def import_imdb(
    ctx: typer.Context,
    source_dir: Annotated[
        Path | None,
        typer.Option(
            "--source-dir",
            help=(
                "Directory holding the datasets, compressed or already decompressed."
                " Default: <data-dir>/downloads."
            ),
        ),
    ] = None,
) -> None:
    """Imports the IMDb datasets into the `titles` table.

    Episodes are processed after base titles, so that their attachment to the
    parent series finds an existing row.
    """
    settings = get_context(ctx).settings
    directory = source_dir if source_dir is not None else settings.downloads_dir

    basics_path = locate_dataset(ImdbDataset.BASICS, directory)
    episode_path = locate_dataset(ImdbDataset.EPISODE, directory)
    console.print(f"Basics:  {basics_path}")
    console.print(f"Episode: {episode_path}")

    with connect(settings.database_path) as conn:
        ensure_current(conn)
        imports = ImportsRepository(conn)

        basics_count = _import_with_progress(
            f"Importing {basics_path.name}",
            basics_path,
            lambda on_progress: import_basics(conn, basics_path, progress=on_progress),
        )
        imports.record(
            ImportRow(
                source=ImportSource.BASICS, file_name=basics_path.name, row_count=basics_count
            )
        )
        console.print(f"  {basics_count:,} titles".replace(",", " "))

        episode_count = _import_with_progress(
            f"Importing {episode_path.name}",
            episode_path,
            lambda on_progress: import_episodes(conn, episode_path, progress=on_progress),
        )
        imports.record(
            ImportRow(
                source=ImportSource.EPISODE, file_name=episode_path.name, row_count=episode_count
            )
        )
        console.print(f"  {episode_count:,} episodes linked".replace(",", " "))


def _import_with_progress(label: str, path: Path, run: Callable[[ProgressCallback], int]) -> int:
    """Runs one import step, with a progress bar driven by bytes read from `path`.

    Based on the file's size on disk, not a row count: `import_basics`/
    `import_episodes` deliberately never pre-count rows, which for `title.basics`
    would mean a first full pass over a gigabyte-plus file for no other purpose.
    """
    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    with progress:
        task = progress.add_task(label, total=path.stat().st_size)

        def on_progress(current: int, total: int) -> None:
            progress.update(task, completed=current, total=total)

        return run(on_progress)
