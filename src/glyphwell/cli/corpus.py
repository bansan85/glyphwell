"""Sous-commandes ``glyphwell corpus``.

STATUT : commandes câblées, traitements en attente d'implémentation.
"""

from pathlib import Path
from typing import Annotated

import typer

from glyphwell.cli.context import get_context
from glyphwell.corpus.opus import DEFAULT_CORPUS, DEFAULT_VERSION

__all__ = ["app"]

app = typer.Typer(
    help="Téléchargement, indexation et rafraîchissement du corpus de sous-titres.",
    no_args_is_help=True,
)


@app.command("fetch")
def fetch(
    ctx: typer.Context,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Code de langue OPUS. Défaut : celui du .env"),
    ] = None,
    version: Annotated[
        str,
        typer.Option("--version", help="Release OPUS visée."),
    ] = DEFAULT_VERSION,
    corpus_name: Annotated[
        str,
        typer.Option("--corpus", help="Nom du corpus OPUS."),
    ] = DEFAULT_CORPUS,
    dest: Annotated[
        Path | None,
        typer.Option("--dest", help="Répertoire d'extraction. Défaut : <data-dir>/corpus"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-télécharge même si l'archive est déjà présente."),
    ] = False,
) -> None:
    """Télécharge et extrait le corpus (format `raw`, une seule langue).

    Prévoir plusieurs dizaines de Go pour l'anglais complet.
    """
    settings = get_context(ctx).settings
    _ = (settings, language, version, corpus_name, dest, force)
    raise NotImplementedError


@app.command("index")
def index(
    ctx: typer.Context,
    rehash: Annotated[
        bool,
        typer.Option("--rehash", help="Recalcule l'empreinte des fichiers déjà catalogués."),
    ] = False,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Restreint le scan à une langue."),
    ] = None,
) -> None:
    """Parcourt le corpus extrait et alimente la table `subtitle_files`.

    Ne lit pas le contenu des sous-titres : seuls le chemin, la taille et l'empreinte sont
    relevés. Les identifiants IMDb proviennent de l'arborescence.
    """
    settings = get_context(ctx).settings
    _ = (settings, rehash, language)
    raise NotImplementedError


@app.command("refresh")
def refresh(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Liste ce qui serait invalidé, sans rien écrire."),
    ] = False,
) -> None:
    """Détecte les sous-titres modifiés et invalide leurs résultats.

    Recalcule l'empreinte de chaque fichier catalogué. Si elle diffère, seuls les résultats
    de ce fichier sont supprimés et son curseur remis à zéro dans chaque recherche : le reste
    des recherches est conservé.
    """
    settings = get_context(ctx).settings
    _ = (settings, dry_run)
    raise NotImplementedError
