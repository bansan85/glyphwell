"""Sous-commandes ``glyphwell search``.

STATUT : commandes câblées, traitements en attente d'implémentation.
"""

from pathlib import Path
from typing import Annotated

import typer

from glyphwell.cli.context import get_context
from glyphwell.search.results import ExportFormat

__all__ = ["app"]

app = typer.Typer(
    help="Lancement, reprise, suivi et export des recherches.",
    no_args_is_help=True,
)


@app.command("run")
def run(
    ctx: typer.Context,
    manifest: Annotated[
        Path,
        typer.Argument(help="Manifeste YAML décrivant la recherche.", exists=True, dir_okay=False),
    ],
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Nombre maximal de fichiers, pour un essai."),
    ] = None,
    concurrency: Annotated[
        int | None,
        typer.Option("--concurrency", min=1, help="Fenêtres analysées en parallèle."),
    ] = None,
) -> None:
    """Lance une recherche sur le corpus indexé.

    Une recherche non terminée portant le même hash de manifeste est reprise plutôt que
    dupliquée. Le modèle est vérifié auprès d'Ollama avant tout parcours du corpus.
    """
    settings = get_context(ctx).settings
    _ = (settings, manifest, limit, concurrency)
    raise NotImplementedError


@app.command("resume")
def resume(
    ctx: typer.Context,
    run_id: Annotated[int, typer.Argument(help="Identifiant de la recherche à reprendre.")],
    limit: Annotated[
        int | None,
        typer.Option("--limit", min=1, help="Nombre maximal de fichiers à traiter."),
    ] = None,
) -> None:
    """Reprend une recherche interrompue, à la ligne où elle s'était arrêtée.

    Le manifeste est relu depuis l'instantané archivé au lancement, pas depuis le disque :
    la reprise emploie exactement le prompt et le fenêtrage d'origine.
    """
    settings = get_context(ctx).settings
    _ = (settings, run_id, limit)
    raise NotImplementedError


@app.command("status")
def status(
    ctx: typer.Context,
    run_id: Annotated[
        int | None,
        typer.Argument(help="Recherche à détailler. Sans argument : liste tout."),
    ] = None,
) -> None:
    """Affiche l'avancement des recherches."""
    settings = get_context(ctx).settings
    _ = (settings, run_id)
    raise NotImplementedError


@app.command("export")
def export(
    ctx: typer.Context,
    run_id: Annotated[int, typer.Argument(help="Recherche à exporter.")],
    export_format: Annotated[
        ExportFormat,
        typer.Option("--format", "-f", help="Format de sortie."),
    ] = ExportFormat.JSONL,
    dest: Annotated[
        Path | None,
        typer.Option("--dest", "-o", help="Fichier de sortie. Défaut : <data-dir>/exports/"),
    ] = None,
    matched_only: Annotated[
        bool,
        typer.Option("--matched-only/--all", help="N'exporter que les correspondances."),
    ] = True,
) -> None:
    """Exporte les résultats d'une recherche.

    Les titres sont résolus au moment de l'export : un ré-import des datasets IMDb améliore
    les exports suivants sans toucher aux résultats déjà enregistrés.
    """
    settings = get_context(ctx).settings
    _ = (settings, run_id, export_format, dest, matched_only)
    raise NotImplementedError
