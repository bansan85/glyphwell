"""Point d'entrée de la ligne de commande.

Le callback racine résout la configuration une fois et la dépose dans le contexte Typer :
les sous-commandes n'ont ainsi ni à relire l'environnement ni à reconstruire un `Settings`.
"""

from pathlib import Path
from typing import Annotated

import typer

from glyphwell import __version__
from glyphwell.cli import corpus, db, metadata, search
from glyphwell.cli.context import AppContext, get_context
from glyphwell.config import LogLevel, Settings
from glyphwell.errors import GlyphwellError
from glyphwell.logging import setup_logging

__all__ = ["AppContext", "app", "get_context", "main"]


app = typer.Typer(
    name="glyphwell",
    help=(
        "Recherche pilotée par LLM sur le corpus de sous-titres OpenSubtitles : "
        "téléchargement du corpus, résolution des titres IMDb, recherche reprenable "
        "via Ollama."
    ),
    no_args_is_help=True,
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

app.add_typer(db.app, name="db")
app.add_typer(corpus.app, name="corpus")
app.add_typer(metadata.app, name="metadata")
app.add_typer(search.app, name="search")


def _version_callback(value: bool) -> None:
    """Affiche la version puis termine, comme le veut la convention `--version`."""
    if value:
        typer.echo(f"glyphwell {__version__}")
        raise typer.Exit


@app.callback()
def root(
    ctx: typer.Context,
    data_dir: Annotated[
        Path | None,
        typer.Option(
            "--data-dir",
            help="Racine des données (corpus, datasets, base). Défaut : ./data",
            envvar="GLYPHWELL_DATA_DIR",
        ),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(
            "--database",
            help="Chemin de la base SQLite. Défaut : <data-dir>/glyphwell.db",
            envvar="GLYPHWELL_DATABASE",
        ),
    ] = None,
    log_level: Annotated[
        LogLevel | None,
        typer.Option("--log-level", help="Verbosité de la journalisation."),
    ] = None,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Affiche la version et quitte.",
        ),
    ] = False,
) -> None:
    """Options communes à toutes les sous-commandes."""
    # `Settings` lit l'environnement et le `.env` ; les options explicites l'emportent.
    # On reconstruit l'objet au lieu de le muter, pour que les valeurs venues de la ligne de
    # commande passent elles aussi par la validation pydantic.
    from_env = Settings()
    settings = Settings(
        data_dir=from_env.data_dir if data_dir is None else data_dir,
        database=from_env.database if database is None else database,
        log_level=from_env.log_level if log_level is None else log_level,
    )

    setup_logging(settings.log_level)
    ctx.obj = AppContext(settings=settings)


def main() -> None:
    """Lance la CLI en présentant les erreurs attendues sans trace de pile."""
    try:
        app()
    except GlyphwellError as exc:
        typer.secho(f"Erreur : {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
