"""Subcommands ``glyphwell db``."""

from typing import Annotated

import typer
from rich.table import Table

from glyphwell.cli.context import get_context
from glyphwell.console import console
from glyphwell.db import connect, current_version, initialize

__all__ = ["app"]

app = typer.Typer(
    help="Creation, inspection and maintenance of the SQLite database.", no_args_is_help=True
)


# Tables listed by `db status`, in an order that follows the workflow.
_COUNTED_TABLES = (
    "titles",
    "subtitle_files",
    "runs",
    "run_files",
    "results",
)


@app.command("init")
def init(ctx: typer.Context) -> None:
    """Creates the database and its schema, or upgrades it if it already exists."""
    settings = get_context(ctx).settings
    settings.ensure_directories()
    path = settings.database_path

    with connect(path, create=True) as conn:
        version = initialize(conn)

    console.print(f"Database ready: [bold]{path}[/bold] (schema version {version})")


@app.command("status")
def status(ctx: typer.Context) -> None:
    """Displays the schema version and the row counts of the main tables."""
    settings = get_context(ctx).settings
    path = settings.database_path

    with connect(path) as conn:
        version = current_version(conn)
        counts = {
            table: int(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in _COUNTED_TABLES
        }

    console.print(f"Database: [bold]{path}[/bold]")
    console.print(f"Schema: version {version}")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Table")
    table.add_column("Rows", justify="right")
    for name, count in counts.items():
        table.add_row(name, f"{count:,}".replace(",", " "))
    console.print(table)


@app.command("vacuum")
def vacuum(
    ctx: typer.Context,
    analyze: Annotated[
        bool,
        typer.Option("--analyze/--no-analyze", help="Also refreshes the statistics."),
    ] = True,
) -> None:
    """Compacts the database and refreshes its statistics.

    Useful after a massive invalidation: deletions from `results` leave free pages
    that SQLite does not return to the system on its own.
    """
    settings = get_context(ctx).settings

    with connect(settings.database_path) as conn:
        conn.execute("VACUUM")
        if analyze:
            conn.execute("ANALYZE")

    console.print("Database compacted.")
