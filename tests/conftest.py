"""Shared fixtures."""

import sqlite3
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from glyphwell.config import Settings
from glyphwell.db import connect, initialize_catalog, initialize_run

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def sample_corpus() -> Path:
    """Root of the fabricated mini-corpus, matching the expected OPUS directory tree."""
    return DATA_DIR / "corpus"


@pytest.fixture
def sample_subtitle(sample_corpus: Path) -> Path:
    """A sample subtitle file."""
    return sample_corpus / "en" / "1999" / "0133093" / "3660124.xml"


@pytest.fixture
def sample_archive(tmp_path: Path, sample_subtitle: Path) -> Path:
    """Minimal archive, modeled after an OPUS one: the zip *is* the corpus.

    Contains a valid subtitle, a directory entry, an extensionless service file like the
    ones OPUS archives carry, and a member with an unexpected extension — the three
    categories that `CorpusArchive.summarize` must distinguish.
    """
    path = tmp_path / "OpenSubtitles_v2018_raw_en.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("OpenSubtitles/raw/en/", "")
        archive.writestr(
            "OpenSubtitles/raw/en/1999/0133093/3660124.xml",
            sample_subtitle.read_text(encoding="utf-8"),
        )
        archive.writestr("OpenSubtitles/README", "OPUS corpus")
        archive.writestr("OpenSubtitles/raw/en/1999/0133093/3660125.xml.gz", "compressed")
    return path


@pytest.fixture
def minimal_manifest() -> Path:
    """Manifest reduced to the required fields."""
    return DATA_DIR / "searches" / "minimal.yaml"


@pytest.fixture
def example_manifest() -> Path:
    """The example manifest shipped with the project, which must stay valid."""
    return Path(__file__).parent.parent / "searches" / "example.yaml"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Configuration isolated in a temporary directory.

    `_env_file=None` neutralizes the repo's `.env`: a test must not depend on the local
    configuration of the machine.
    """
    return Settings(data_dir=tmp_path / "data", _env_file=None)


@pytest.fixture
def catalog_db(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Temporary catalog database (titles, subtitle_files, corpus_downloads, imports)."""
    with connect(settings.catalog_database_path, create=True) as conn:
        initialize_catalog(conn)
        yield conn


@pytest.fixture
def run_db(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Temporary run database (runs, run_files, results)."""
    with connect(settings.data_dir / "run.db", create=True) as conn:
        initialize_run(conn)
        yield conn
