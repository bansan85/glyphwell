"""Sous-commandes ``glyphwell metadata``.

STATUT : commandes câblées, traitements en attente d'implémentation.
"""

from typing import Annotated

import typer

from glyphwell.cli.context import get_context

__all__ = ["app"]

app = typer.Typer(
    help="Téléchargement et import des métadonnées de titres depuis les datasets IMDb.",
    no_args_is_help=True,
)


@app.command("fetch-imdb")
def fetch_imdb(
    ctx: typer.Context,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-télécharge même si les fichiers sont présents."),
    ] = False,
) -> None:
    """Télécharge `title.basics.tsv.gz` et `title.episode.tsv.gz`.

    Datasets non commerciaux IMDb : aucune clé API, republiés chaque jour.
    """
    settings = get_context(ctx).settings
    _ = (settings, force)
    raise NotImplementedError


@app.command("import-imdb")
def import_imdb(ctx: typer.Context) -> None:
    """Importe les datasets IMDb dans la table `titles`.

    Les épisodes sont traités après les titres de base, afin que leur rattachement à la
    série parente trouve une ligne existante.
    """
    settings = get_context(ctx).settings
    _ = settings
    raise NotImplementedError
