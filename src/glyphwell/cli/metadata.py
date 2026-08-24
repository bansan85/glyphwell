"""Subcommands ``glyphwell metadata``.

STATUS: commands wired up, processing pending implementation.
"""

from typing import Annotated

import typer

from glyphwell.cli.context import get_context

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
    _ = (settings, force)
    raise NotImplementedError


@app.command("import-imdb")
def import_imdb(ctx: typer.Context) -> None:
    """Imports the IMDb datasets into the `titles` table.

    Episodes are processed after base titles, so that their attachment to the
    parent series finds an existing row.
    """
    settings = get_context(ctx).settings
    _ = settings
    raise NotImplementedError
