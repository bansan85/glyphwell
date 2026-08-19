"""Sous-commandes ``glyphwell db``."""

from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from glyphwell.cli.context import get_context
from glyphwell.db import connect, current_version, initialize

__all__ = ["app"]

app = typer.Typer(help="Création, inspection et entretien de la base SQLite.", no_args_is_help=True)

_console = Console()

# Tables listées par `db status`, dans un ordre qui suit le flux de travail.
_COUNTED_TABLES = (
    "titles",
    "subtitle_files",
    "runs",
    "run_files",
    "results",
)


@app.command("init")
def init(ctx: typer.Context) -> None:
    """Crée la base et son schéma, ou la met à niveau si elle existe déjà."""
    settings = get_context(ctx).settings
    settings.ensure_directories()
    path = settings.database_path

    with connect(path, create=True) as conn:
        version = initialize(conn)

    _console.print(f"Base prête : [bold]{path}[/bold] (schéma version {version})")


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Affiche la version du schéma et le remplissage des tables principales."""
    settings = get_context(ctx).settings
    path = settings.database_path

    with connect(path) as conn:
        version = current_version(conn)
        counts = {
            table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in _COUNTED_TABLES
        }

    _console.print(f"Base : [bold]{path}[/bold]")
    _console.print(f"Schéma : version {version}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Table")
    table.add_column("Lignes", justify="right")
    for name, count in counts.items():
        table.add_row(name, f"{count:,}".replace(",", " "))
    _console.print(table)


@app.command("vacuum")
def vacuum(
    ctx: typer.Context,
    analyze: Annotated[
        bool,
        typer.Option("--analyze/--no-analyze", help="Rafraîchit aussi les statistiques."),
    ] = True,
) -> None:
    """Compacte la base et rafraîchit ses statistiques.

    Utile après une invalidation massive : les suppressions de `results` laissent des pages
    libres que SQLite ne rend pas au système de lui-même.
    """
    settings = get_context(ctx).settings

    with connect(settings.database_path) as conn:
        conn.execute("VACUUM")
        if analyze:
            conn.execute("ANALYZE")

    _console.print("Base compactée.")
