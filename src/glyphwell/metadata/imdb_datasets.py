"""Official IMDb datasets — primary source of titles.

Two files are enough:

* ``title.basics.tsv.gz``: type, title, year, runtime, adult flag, genres;
* ``title.episode.tsv.gz``: an episode's link to its series, season, number.

They are **indexed by ``tconst``**, exactly the identifier carried by the OPUS corpus
tree: the join is direct, offline, and requires no API key. This is the project's only
source of metadata.

Format pitfall: the null value is the literal string ``\\N``, not an empty string.

STATUS: stubs, apart from constants.
"""

import sqlite3
from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Final

__all__ = [
    "BASE_URL",
    "NULL_MARKER",
    "ImdbDataset",
    "download",
    "import_basics",
    "import_episodes",
    "iter_rows",
]

BASE_URL: Final = "https://datasets.imdbws.com/"
"""IMDb's non-commercial datasets, republished daily."""

NULL_MARKER: Final = r"\N"
"""Marker for a missing value in IMDb TSVs. Distinct from the empty string."""


class ImdbDataset(StrEnum):
    """Datasets used. The value is the file name, hence also the URL suffix."""

    BASICS = "title.basics.tsv.gz"
    EPISODE = "title.episode.tsv.gz"

    @property
    def url(self) -> str:
        """Download URL for the dataset."""
        return f"{BASE_URL}{self.value}"


def download(dataset: ImdbDataset, *, dest_dir: Path, force: bool = False) -> Path:
    """Downloads a dataset and returns the local file path.

    Args:
        dataset: dataset to download.
        dest_dir: destination directory.
        force: re-download even if the file already exists.

    Returns:
        The local ``.tsv.gz`` path.

    Raises:
        MetadataError: download failed.
    """
    raise NotImplementedError


def iter_rows(path: Path) -> Iterator[Mapping[str, str | None]]:
    """Yields the rows of an IMDb TSV, header used as column names.

    Generator: ``title.basics`` has more than ten million rows. ``\\N`` values are
    converted to `None`.

    Raises:
        MetadataError: file unreadable or unexpected header.
    """
    raise NotImplementedError


def import_basics(conn: sqlite3.Connection, path: Path, *, batch_size: int = 10_000) -> int:
    """Imports ``title.basics`` into `titles` and returns the number of rows written.

    Written in batches, one transaction per batch: an interrupted import leaves the
    database consistent and can be re-run without duplication (upsert on `imdb_id`).

    Raises:
        MetadataError: file unreadable.
        DatabaseError: write failed.
    """
    raise NotImplementedError


def import_episodes(conn: sqlite3.Connection, path: Path, *, batch_size: int = 10_000) -> int:
    """Imports ``title.episode`` and completes `titles` (parent, season, episode).

    Must run after `import_basics`: episodes must already exist as titles.

    Raises:
        MetadataError: file unreadable.
        DatabaseError: write failed.
    """
    raise NotImplementedError
