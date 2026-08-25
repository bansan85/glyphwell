"""Official IMDb datasets — primary source of titles.

Two files are enough:

* ``title.basics.tsv.gz``: type, title, year, runtime, adult flag, genres;
* ``title.episode.tsv.gz``: an episode's link to its series, season, number.

They are **indexed by ``tconst``**, exactly the identifier carried by the OPUS corpus
tree: the join is direct, offline, and requires no API key. This is the project's only
source of metadata.

Format pitfall: the null value is the literal string ``\\N``, not an empty string.

Unlike the OPUS archive (tens of GB, see `glyphwell.corpus.opus`), these files are a few
hundred MB at most: a plain download with no resume support is enough.
"""

import csv
import gzip
import io
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import IO, BinaryIO, Final

import httpx

from glyphwell.db.repositories import EpisodeLink, TitleRow, TitlesRepository
from glyphwell.errors import MetadataError
from glyphwell.http import make_client
from glyphwell.logging import get_logger

__all__ = [
    "BASE_URL",
    "NULL_MARKER",
    "ImdbDataset",
    "ProgressCallback",
    "download",
    "import_basics",
    "import_episodes",
    "iter_rows",
    "locate_dataset",
]

type ProgressCallback = Callable[[int, int], None]
"""Progress callback: bytes read so far, total size of the TSV on disk.

Based on the file's size, not a row count: counting rows first would mean a full read
of a file that can exceed a gigabyte, defeating the point of reporting progress before
the import is done.
"""

_log = get_logger(__name__)

BASE_URL: Final = "https://datasets.imdbws.com/"
"""IMDb's non-commercial datasets, republished daily."""

NULL_MARKER: Final = r"\N"
"""Marker for a missing value in IMDb TSVs. Distinct from the empty string."""

_CHUNK_SIZE: Final = 1 << 20
_PART_SUFFIX: Final = ".part"

_DEFAULT_BATCH_SIZE: Final = 50_000
"""Rows per transaction for `import_basics`/`import_episodes`.

Measured on the real datasets: raising this from an initial 10 000 to 50 000 cuts
wall-clock time by about 25% (fewer WAL commits) with no measurable regression: an
interrupted import redoes at most one batch, still a few seconds of idempotent upsert
work, not the drama a huge batch would be if it required rolling back manual changes.
"""

_PROGRESS_ROWS: Final = _DEFAULT_BATCH_SIZE
"""How often `_basics_rows`/`_episode_links` report progress, in rows read.

Frequent enough that a progress bar feels live, rare enough that the callback itself
never becomes part of the hot per-row loop.
"""


class ImdbDataset(StrEnum):
    """Datasets used. The value is the file name, hence also the URL suffix."""

    BASICS = "title.basics.tsv.gz"
    EPISODE = "title.episode.tsv.gz"

    @property
    def url(self) -> str:
        """Download URL for the dataset."""
        return f"{BASE_URL}{self.value}"


def download(
    dataset: ImdbDataset,
    *,
    dest_dir: Path,
    force: bool = False,
    client: httpx.Client | None = None,
) -> Path:
    """Downloads a dataset and returns the local file path.

    Args:
        dataset: dataset to download.
        dest_dir: destination directory.
        force: re-download even if the file already exists.
        client: HTTP client to reuse, otherwise a throwaway client is created.

    Returns:
        The local ``.tsv.gz`` path.

    Raises:
        MetadataError: download failed.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / dataset.value
    if dest.is_file() and not force:
        _log.info("dataset already present, download skipped: %s", dest)
        return dest

    part = dest.with_name(dest.name + _PART_SUFFIX)
    owned = client is None
    http = client if client is not None else make_client()
    try:
        with http.stream("GET", dataset.url) as response:
            response.raise_for_status()
            with part.open("wb") as handle:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    handle.write(chunk)
    except httpx.HTTPError as exc:
        message = f"download failed ({dataset.url}): {exc}"
        raise MetadataError(message) from exc
    except OSError as exc:
        message = f"cannot write to {part}: {exc}"
        raise MetadataError(message) from exc
    finally:
        if owned:
            http.close()

    part.replace(dest)
    return dest


def locate_dataset(dataset: ImdbDataset, directory: Path) -> Path:
    """Finds a dataset file in `directory`, compressed or already decompressed.

    `download` always names its file ``*.tsv.gz``, but a user who fetched the datasets
    by hand (IMDb's own download page decompresses them) may only have the plain
    ``*.tsv``. Both are accepted so `import-imdb` can point at either.

    Raises:
        MetadataError: neither form is present in `directory`.
    """
    compressed = directory / dataset.value
    if compressed.is_file():
        return compressed
    decompressed = directory / dataset.value.removesuffix(".gz")
    if decompressed.is_file():
        return decompressed
    message = (
        f"neither {compressed.name} nor {decompressed.name} found in {directory}."
        " Run `glyphwell metadata fetch-imdb` first, or pass --source-dir."
    )
    raise MetadataError(message)


def _open_text(path: Path) -> IO[str]:
    """Opens a TSV for text reading, transparently decompressing ``.gz``."""
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8", newline="")
    return path.open(mode="rt", encoding="utf-8", newline="")


def iter_rows(path: Path) -> Iterator[Mapping[str, str | None]]:
    """Yields the rows of an IMDb TSV, header used as column names.

    Generator: ``title.basics`` has more than ten million rows. ``\\N`` values are
    converted to `None`.

    Plain `csv.reader`, not `DictReader`: at this row count, `DictReader`'s per-row
    bookkeeping for ragged rows (``restkey``/``restval``) is measurable overhead that
    every real IMDb row never needs, since the column count always matches the header.

    Raises:
        MetadataError: file unreadable, unexpected header, or a row whose column count
            doesn't match the header.
    """
    try:
        handle = _open_text(path)
    except OSError as exc:
        message = f"cannot read {path}: {exc}"
        raise MetadataError(message) from exc

    try:
        # `QUOTE_NONE`: IMDb TSVs are not CSV-quoted. Titles routinely start with a
        # literal `"` (about 5 500 of them in `title.basics`, e.g. `"Giliap"`, a real
        # title, not an escaped one) — the default dialect would treat it as a quoted
        # field and silently strip the quotes instead of preserving them.
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            fieldnames = next(reader)
        except StopIteration:
            message = f"empty dataset: {path}"
            raise MetadataError(message) from None

        for row_number, values in enumerate(reader, start=2):
            try:
                yield {
                    name: None if value == NULL_MARKER else value
                    for name, value in zip(fieldnames, values, strict=True)
                }
            except ValueError as exc:
                message = f"{path}:{row_number}: {exc}"
                raise MetadataError(message) from exc
    finally:
        handle.close()


@dataclass(frozen=True, slots=True, kw_only=True)
class _TsvSource:
    """A TSV opened for positional reading, with byte-based progress built in."""

    handle: IO[str]
    fieldnames: list[str]
    rows: Iterator[tuple[int, list[str]]]
    tell: Callable[[], int]
    """Bytes consumed from `path` on disk so far — compressed bytes for a ``.gz``.

    Bound to the *raw binary* handle rather than `handle.tell()`: `TextIOWrapper` (and
    `gzip.GzipFile` wrapped in one) returns an opaque seek cookie there, not a byte
    count, whereas the raw handle's position is exactly what advances as bytes are
    pulled off disk.
    """
    total_size: int
    """`path`'s size on disk, i.e. what `tell()` counts up to."""


def _open_rows(path: Path) -> _TsvSource:
    """Opens `path` for positional reading: no per-row dict, unlike `iter_rows`.

    `import_basics`/`import_episodes` only ever build a `TitleRow`/`EpisodeLink` from
    each row; going through `iter_rows`'s `Mapping` meant building and discarding a
    dict for every one of `title.basics`'s ten-million-plus rows, which measured out to
    close to half of `import_basics`'s wall-clock time. Reading positionally instead —
    resolving each needed column's index once, then indexing straight into the row's
    `list[str]` — removes that dict entirely while still going through the same typed
    `TitleRow`/`EpisodeLink` objects the repositories expect.

    Raises:
        MetadataError: file unreadable or empty.
    """
    try:
        total_size = path.stat().st_size
        raw: BinaryIO = path.open("rb")
    except OSError as exc:
        message = f"cannot read {path}: {exc}"
        raise MetadataError(message) from exc

    try:
        binary = gzip.GzipFile(fileobj=raw) if path.suffix == ".gz" else raw
        handle: IO[str] = io.TextIOWrapper(binary, encoding="utf-8", newline="")
        # `QUOTE_NONE`: see `iter_rows`.
        reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        try:
            fieldnames = next(reader)
        except StopIteration:
            message = f"empty dataset: {path}"
            raise MetadataError(message) from None
    except Exception:
        raw.close()
        raise

    def rows() -> Iterator[tuple[int, list[str]]]:
        for row_number, values in enumerate(reader, start=2):
            if len(values) != len(fieldnames):
                message = f"{path}:{row_number}: {len(values)} columns, expected {len(fieldnames)}"
                raise MetadataError(message)
            yield row_number, values

    return _TsvSource(
        handle=handle, fieldnames=fieldnames, rows=rows(), tell=raw.tell, total_size=total_size
    )


def _column_index(fieldnames: list[str], name: str, path: Path) -> int:
    """Resolves a column's position in the header, raising `MetadataError` if absent."""
    try:
        return fieldnames.index(name)
    except ValueError as exc:
        message = f"missing column '{name}' in {path}"
        raise MetadataError(message) from exc


def _or_none(value: str) -> str | None:
    return None if value == NULL_MARKER else value


def _int_or_none(value: str) -> int | None:
    return None if value == NULL_MARKER else int(value)


def _report(source: _TsvSource, progress: ProgressCallback | None, row_number: int) -> None:
    """Calls `progress` every `_PROGRESS_ROWS` rows — never on every row."""
    if progress is not None and row_number % _PROGRESS_ROWS == 0:
        progress(source.tell(), source.total_size)


def _basics_rows(path: Path, *, progress: ProgressCallback | None = None) -> Iterator[TitleRow]:
    """Reads ``title.basics.tsv`` straight into `TitleRow`. See `_open_rows`.

    The parent link is always `None` here: it is only known once `import_episodes` has
    run, and `TitlesRepository.upsert_many` preserves whatever it already finds.
    """
    source = _open_rows(path)
    fieldnames = source.fieldnames
    i_tconst = _column_index(fieldnames, "tconst", path)
    i_type = _column_index(fieldnames, "titleType", path)
    i_primary = _column_index(fieldnames, "primaryTitle", path)
    i_original = _column_index(fieldnames, "originalTitle", path)
    i_adult = _column_index(fieldnames, "isAdult", path)
    i_start = _column_index(fieldnames, "startYear", path)
    i_end = _column_index(fieldnames, "endYear", path)
    i_runtime = _column_index(fieldnames, "runtimeMinutes", path)
    try:
        for row_number, values in source.rows:
            tconst = values[i_tconst]
            if tconst == NULL_MARKER:
                message = f"missing or null 'tconst' in {path}:{row_number}"
                raise MetadataError(message)
            try:
                yield TitleRow(
                    imdb_id=tconst,
                    title_type=_or_none(values[i_type]),
                    primary_title=_or_none(values[i_primary]),
                    original_title=_or_none(values[i_original]),
                    start_year=_int_or_none(values[i_start]),
                    end_year=_int_or_none(values[i_end]),
                    is_adult=values[i_adult] == "1",
                    runtime_minutes=_int_or_none(values[i_runtime]),
                    parent_imdb_id=None,
                    season_number=None,
                    episode_number=None,
                )
            except ValueError as exc:
                message = f"malformed row in {path}:{row_number}: {exc}"
                raise MetadataError(message) from exc
            _report(source, progress, row_number)
        if progress is not None:
            progress(source.total_size, source.total_size)
    finally:
        source.handle.close()


def _episode_links(
    path: Path, *, progress: ProgressCallback | None = None
) -> Iterator[EpisodeLink]:
    """Reads ``title.episode.tsv`` straight into `EpisodeLink`. See `_open_rows`."""
    source = _open_rows(path)
    fieldnames = source.fieldnames
    i_tconst = _column_index(fieldnames, "tconst", path)
    i_parent = _column_index(fieldnames, "parentTconst", path)
    i_season = _column_index(fieldnames, "seasonNumber", path)
    i_episode = _column_index(fieldnames, "episodeNumber", path)
    try:
        for row_number, values in source.rows:
            tconst = values[i_tconst]
            parent = values[i_parent]
            if tconst == NULL_MARKER or parent == NULL_MARKER:
                message = f"missing or null 'tconst'/'parentTconst' in {path}:{row_number}"
                raise MetadataError(message)
            try:
                yield EpisodeLink(
                    imdb_id=tconst,
                    parent_imdb_id=parent,
                    season_number=_int_or_none(values[i_season]),
                    episode_number=_int_or_none(values[i_episode]),
                )
            except ValueError as exc:
                message = f"malformed row in {path}:{row_number}: {exc}"
                raise MetadataError(message) from exc
            _report(source, progress, row_number)
        if progress is not None:
            progress(source.total_size, source.total_size)
    finally:
        source.handle.close()


def _run_in_batches[T](
    items: Iterator[T],
    *,
    batch_size: int,
    conn: sqlite3.Connection,
    write: Callable[[list[T]], int],
) -> int:
    """Commits `write` in batches, one transaction each.

    An interrupted import leaves the database consistent: each batch is either fully
    committed or, on error, rolled back before the exception propagates.
    """
    written = 0
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            written += _commit_batch(conn, batch, write)
            batch = []
    if batch:
        written += _commit_batch(conn, batch, write)
    return written


def _commit_batch[T](
    conn: sqlite3.Connection, batch: list[T], write: Callable[[list[T]], int]
) -> int:
    conn.execute("BEGIN")
    try:
        written = write(batch)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return written


def import_basics(
    conn: sqlite3.Connection,
    path: Path,
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    progress: ProgressCallback | None = None,
) -> int:
    """Imports ``title.basics`` into `titles` and returns the number of rows written.

    Written in batches, one transaction per batch: an interrupted import leaves the
    database consistent and can be re-run without duplication (upsert on `imdb_id`).

    Args:
        conn: destination database connection.
        path: ``title.basics.tsv`` or ``title.basics.tsv.gz``.
        batch_size: rows per transaction.
        progress: called with (bytes read, total bytes) every `_PROGRESS_ROWS` rows.

    Raises:
        MetadataError: file unreadable.
        DatabaseError: write failed.
    """
    repo = TitlesRepository(conn)
    rows = _basics_rows(path, progress=progress)
    return _run_in_batches(rows, batch_size=batch_size, conn=conn, write=repo.upsert_many)


def import_episodes(
    conn: sqlite3.Connection,
    path: Path,
    *,
    batch_size: int = _DEFAULT_BATCH_SIZE,
    progress: ProgressCallback | None = None,
) -> int:
    """Imports ``title.episode`` and completes `titles` (parent, season, episode).

    Must run after `import_basics`: episodes must already exist as titles.

    Args:
        conn: destination database connection.
        path: ``title.episode.tsv`` or ``title.episode.tsv.gz``.
        batch_size: rows per transaction.
        progress: called with (bytes read, total bytes) every `_PROGRESS_ROWS` rows.

    Raises:
        MetadataError: file unreadable.
        DatabaseError: write failed.
    """
    repo = TitlesRepository(conn)
    links = _episode_links(path, progress=progress)
    return _run_in_batches(
        links, batch_size=batch_size, conn=conn, write=repo.set_episode_links_many
    )
