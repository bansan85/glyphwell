"""Command-line entry point.

The root callback resolves the configuration once and stores it in the Typer context:
subcommands thus never need to re-read the environment or rebuild a `Settings`.
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
        "LLM-driven search over the OpenSubtitles subtitle corpus: "
        "corpus download, IMDb title resolution, resumable search "
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
    """Prints the version then exits, as the `--version` convention dictates."""
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
            help="Data root (corpus, datasets, database). Default: ./data",
            envvar="GLYPHWELL_DATA_DIR",
        ),
    ] = None,
    database: Annotated[
        Path | None,
        typer.Option(
            "--database",
            help="Path to the SQLite database. Default: <data-dir>/glyphwell.db",
            envvar="GLYPHWELL_DATABASE",
        ),
    ] = None,
    log_level: Annotated[
        LogLevel | None,
        typer.Option("--log-level", help="Logging verbosity."),
    ] = None,
    no_check_certificate: Annotated[
        bool,
        typer.Option(
            "--no-check-certificate",
            help=(
                "Do not verify the TLS certificate of the download servers (OPUS, IMDb)."
                " Insecure: a last resort behind a TLS-inspecting proxy, where"
                " SSL_CERT_FILE is the better answer."
            ),
        ),
    ] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Prints the version and exits.",
        ),
    ] = False,
) -> None:
    """Options common to all subcommands."""
    # `Settings` reads the environment and `.env`; explicit options take precedence.
    # The object is rebuilt rather than mutated, so that values coming from the command
    # line also go through pydantic validation.
    from_env = Settings()
    settings = Settings(
        data_dir=from_env.data_dir if data_dir is None else data_dir,
        database=from_env.database if database is None else database,
        log_level=from_env.log_level if log_level is None else log_level,
        # The flag can only *disable* verification, never re-enable what
        # `GLYPHWELL_VERIFY_TLS=false` already gave up on: unlike the options above, its
        # absence is not "no opinion" but the secure default.
        verify_tls=from_env.verify_tls and not no_check_certificate,
    )

    setup_logging(settings.log_level)
    ctx.obj = AppContext(settings=settings)


def main() -> None:
    """Runs the CLI, presenting expected errors without a stack trace."""
    try:
        app()
    except GlyphwellError as exc:
        typer.secho(f"Error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc
