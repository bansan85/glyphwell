"""The CLI is fully wired up: every group and every command exposes its help.

Deliberately shallow test: at this stage most of the processing is stubbed, but
the command tree, options and default values must already be correct — that is
what breaks most quietly when a subcommand is added.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from glyphwell import __version__
from glyphwell.cli import app

runner = CliRunner()

GROUPS = ("db", "corpus", "metadata", "search")

COMMANDS = (
    ("db", "init"),
    ("db", "status"),
    ("db", "vacuum"),
    ("corpus", "fetch"),
    ("corpus", "index"),
    ("corpus", "refresh"),
    ("metadata", "fetch-imdb"),
    ("metadata", "import-imdb"),
    ("search", "run"),
    ("search", "resume"),
    ("search", "status"),
    ("search", "export"),
)


def test_root_help_lists_every_group() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for group in GROUPS:
        assert group in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize("group", GROUPS)
def test_group_help(group: str) -> None:
    result = runner.invoke(app, [group, "--help"])
    assert result.exit_code == 0


@pytest.mark.parametrize(("group", "command"), COMMANDS)
def test_command_help(group: str, command: str) -> None:
    result = runner.invoke(app, [group, command, "--help"])
    assert result.exit_code == 0


def test_db_init_then_status(tmp_path: Path) -> None:
    """The only fully complete chain at this stage: create a database, then inspect it."""
    data_dir = tmp_path / "data"

    created = runner.invoke(app, ["--data-dir", str(data_dir), "db", "init"])
    assert created.exit_code == 0, created.output
    assert (data_dir / "glyphwell.db").exists()

    status = runner.invoke(app, ["--data-dir", str(data_dir), "db", "status"])
    assert status.exit_code == 0, status.output
    assert "subtitle_files" in status.output


def test_status_without_database_fails_cleanly(tmp_path: Path) -> None:
    """A missing database must produce an actionable message, not a stack trace."""
    result = runner.invoke(app, ["--data-dir", str(tmp_path / "empty"), "db", "status"])
    assert result.exit_code != 0
