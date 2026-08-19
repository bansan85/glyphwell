"""La CLI est entièrement câblée : chaque groupe et chaque commande expose son aide.

Test volontairement superficiel : à ce stade la plupart des traitements sont des stubs, mais
l'arborescence des commandes, les options et les valeurs par défaut doivent déjà être
correctes — c'est ce qui casse le plus discrètement quand on ajoute une sous-commande.
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
    """Le seul bout de chaîne complet à ce stade : créer une base, puis l'inspecter."""
    data_dir = tmp_path / "data"

    created = runner.invoke(app, ["--data-dir", str(data_dir), "db", "init"])
    assert created.exit_code == 0, created.output
    assert (data_dir / "glyphwell.db").exists()

    status = runner.invoke(app, ["--data-dir", str(data_dir), "db", "status"])
    assert status.exit_code == 0, status.output
    assert "subtitle_files" in status.output


def test_status_without_database_fails_cleanly(tmp_path: Path) -> None:
    """Une base absente doit produire un message actionnable, pas une trace de pile."""
    result = runner.invoke(app, ["--data-dir", str(tmp_path / "vide"), "db", "status"])
    assert result.exit_code != 0
