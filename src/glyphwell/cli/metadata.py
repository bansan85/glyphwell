"""Subcommands ``glyphwell metadata``."""

from pathlib import Path
from typing import Annotated

import typer

from glyphwell.cli.context import get_context
from glyphwell.console import console
from glyphwell.db import connect, ensure_current
from glyphwell.db.repositories import ImportRow, ImportSource, ImportsRepository
from glyphwell.metadata.imdb_datasets import (
    ImdbDataset,
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

    with connect(settings.database_path) as conn:
        ensure_current(conn)
        imports = ImportsRepository(conn)

        console.print(f"Importing {basics_path}…")
        basics_count = import_basics(conn, basics_path)
        imports.record(
            ImportRow(
                source=ImportSource.BASICS, file_name=basics_path.name, row_count=basics_count
            )
        )
        console.print(f"  {basics_count:,} titles".replace(",", " "))

        console.print(f"Importing {episode_path}…")
        episode_count = import_episodes(conn, episode_path)
        imports.record(
            ImportRow(
                source=ImportSource.EPISODE, file_name=episode_path.name, row_count=episode_count
            )
        )
        console.print(f"  {episode_count:,} episodes linked".replace(",", " "))
