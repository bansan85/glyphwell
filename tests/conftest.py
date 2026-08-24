"""Fixtures partagées."""

import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from glyphwell.config import Settings
from glyphwell.db import connect, initialize

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def sample_corpus() -> Path:
    """Racine du mini-corpus fabriqué, respectant l'arborescence OPUS attendue."""
    return DATA_DIR / "corpus"


@pytest.fixture
def sample_subtitle(sample_corpus: Path) -> Path:
    """Un fichier de sous-titre d'échantillon."""
    return sample_corpus / "en" / "1999" / "0133093" / "3660124.xml"


@pytest.fixture
def sample_archive(tmp_path: Path, sample_subtitle: Path) -> Path:
    """Archive minimale, à l'image de celle d'OPUS : le zip *est* le corpus.

    Contient un sous-titre valide, une entrée de répertoire, un fichier de service sans
    extension comme en embarquent les archives OPUS, et un membre à l'extension inattendue
    — les trois catégories que `CorpusArchive.summarize` doit distinguer.
    """
    path = tmp_path / "OpenSubtitles_v2018_raw_en.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("OpenSubtitles/raw/en/", "")
        archive.writestr(
            "OpenSubtitles/raw/en/1999/0133093/3660124.xml",
            sample_subtitle.read_text(encoding="utf-8"),
        )
        archive.writestr("OpenSubtitles/README", "corpus OPUS")
        archive.writestr("OpenSubtitles/raw/en/1999/0133093/3660125.xml.gz", "compresse")
    return path


@pytest.fixture
def minimal_manifest() -> Path:
    """Manifeste réduit aux champs obligatoires."""
    return DATA_DIR / "searches" / "minimal.yaml"


@pytest.fixture
def example_manifest() -> Path:
    """Le manifeste d'exemple livré avec le projet, qui doit rester valide."""
    return Path(__file__).parent.parent / "searches" / "example.yaml"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Configuration isolée dans un répertoire temporaire.

    `_env_file=None` neutralise le `.env` du dépôt : un test ne doit pas dépendre de la
    configuration locale de la machine.
    """
    return Settings(data_dir=tmp_path / "data", _env_file=None)


@pytest.fixture
def db(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Base temporaire, schéma déjà appliqué."""
    with connect(settings.database_path, create=True) as conn:
        initialize(conn)
        yield conn
