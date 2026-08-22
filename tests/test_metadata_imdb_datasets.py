"""Download, TSV parsing, and import of the IMDb datasets.

Downloads are exercised through `httpx.MockTransport`, injected via the `client`
parameter: no test leaves the machine.
"""

import gzip
import sqlite3
from pathlib import Path

import httpx
import pytest

from glyphwell.db.repositories import TitlesRepository
from glyphwell.errors import MetadataError
from glyphwell.metadata.imdb_datasets import (
    ImdbDataset,
    download,
    import_basics,
    import_episodes,
    iter_rows,
    locate_dataset,
)

BASICS_TSV = (
    "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear"
    "\truntimeMinutes\tgenres\n"
    "tt0133093\tmovie\tThe Matrix\tThe Matrix\t0\t1999\t\\N\t136\tAction,Sci-Fi\n"
    "tt0041038\ttvSeries\tThe Series\tThe Series\t0\t1950\t1955\t\\N\tComedy\n"
    "tt0041039\ttvEpisode\tThe Episode\tThe Episode\t0\t1950\t\\N\t\\N\t\\N\n"
)

EPISODE_TSV = "tconst\tparentTconst\tseasonNumber\tepisodeNumber\ntt0041039\ttt0041038\t1\t9\n"


def _client(*, payload: bytes, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_writes_the_destination_file(tmp_path: Path) -> None:
    with _client(payload=b"gzip-bytes") as http:
        path = download(ImdbDataset.BASICS, dest_dir=tmp_path, client=http)

    assert path == tmp_path / "title.basics.tsv.gz"
    assert path.read_bytes() == b"gzip-bytes"
    assert not path.with_name(path.name + ".part").exists()


def test_download_skips_an_existing_file(tmp_path: Path) -> None:
    dest = tmp_path / ImdbDataset.BASICS.value
    dest.write_bytes(b"already there")

    with _client(payload=b"fresh") as http:
        path = download(ImdbDataset.BASICS, dest_dir=tmp_path, client=http)

    assert path.read_bytes() == b"already there"


def test_download_force_overwrites(tmp_path: Path) -> None:
    dest = tmp_path / ImdbDataset.BASICS.value
    dest.write_bytes(b"stale")

    with _client(payload=b"fresh") as http:
        download(ImdbDataset.BASICS, dest_dir=tmp_path, force=True, client=http)

    assert dest.read_bytes() == b"fresh"


def test_download_reports_an_http_error(tmp_path: Path) -> None:
    with (
        _client(payload=b"", status=503) as http,
        pytest.raises(MetadataError, match="download failed"),
    ):
        download(ImdbDataset.BASICS, dest_dir=tmp_path, client=http)


def test_locate_dataset_prefers_the_compressed_form(tmp_path: Path) -> None:
    (tmp_path / "title.basics.tsv.gz").write_bytes(b"")
    (tmp_path / "title.basics.tsv").write_bytes(b"")

    assert locate_dataset(ImdbDataset.BASICS, tmp_path).name == "title.basics.tsv.gz"


def test_locate_dataset_accepts_an_already_decompressed_file(tmp_path: Path) -> None:
    """A user who downloaded and unpacked the datasets by hand should not have to
    re-download them."""
    (tmp_path / "title.basics.tsv").write_bytes(b"")

    assert locate_dataset(ImdbDataset.BASICS, tmp_path).name == "title.basics.tsv"


def test_locate_dataset_missing_is_reported(tmp_path: Path) -> None:
    with pytest.raises(MetadataError, match=r"title\.basics"):
        locate_dataset(ImdbDataset.BASICS, tmp_path)


def test_iter_rows_converts_the_null_marker(tmp_path: Path) -> None:
    path = tmp_path / "title.basics.tsv"
    path.write_text(BASICS_TSV, encoding="utf-8")

    rows = list(iter_rows(path))
    assert rows[0]["tconst"] == "tt0133093"
    assert rows[0]["endYear"] is None
    assert rows[0]["runtimeMinutes"] == "136"


def test_iter_rows_reports_a_ragged_row(tmp_path: Path) -> None:
    """A row with the wrong column count must be reported, not silently padded.

    `DictReader` would pad a short row with `None` under its missing keys instead of
    raising — exactly the kind of silent corruption `iter_rows` should surface loudly.
    """
    path = tmp_path / "title.basics.tsv"
    path.write_text(
        "tconst\ttitleType\tprimaryTitle\ntt0000001\tshort\n",  # missing the primaryTitle column
        encoding="utf-8",
    )

    with pytest.raises(MetadataError, match=r"title\.basics\.tsv:2"):
        list(iter_rows(path))


def test_iter_rows_preserves_a_literal_leading_quote(tmp_path: Path) -> None:
    """IMDb TSVs are not CSV-quoted: a title starting with `"` is real, not escaping.

    `title.basics.tsv` has about 5 500 such rows (e.g. `"Giliap"`, a 1975 film). The
    default `csv` dialect would treat the leading `"` as opening a quoted field and
    silently strip it.
    """
    path = tmp_path / "title.basics.tsv"
    path.write_text(
        "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear"
        "\truntimeMinutes\tgenres\n"
        'tt0073045\tmovie\t"Giliap"\t"Giliap"\t0\t1975\t\\N\t137\tCrime,Drama\n',
        encoding="utf-8",
    )

    rows = list(iter_rows(path))
    assert rows[0]["primaryTitle"] == '"Giliap"'


def test_iter_rows_reads_a_gzipped_file(tmp_path: Path) -> None:
    path = tmp_path / "title.basics.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write(BASICS_TSV)

    rows = list(iter_rows(path))
    assert len(rows) == 3


def test_import_basics_populates_titles(db: sqlite3.Connection, tmp_path: Path) -> None:
    path = tmp_path / "title.basics.tsv"
    path.write_text(BASICS_TSV, encoding="utf-8")

    written = import_basics(db, path)

    assert written == 3
    found = TitlesRepository(db).get("tt0133093")
    assert found is not None
    assert found.primary_title == "The Matrix"
    assert found.start_year == 1999
    assert found.end_year is None
    assert found.is_adult is False


def test_import_episodes_links_after_basics(db: sqlite3.Connection, tmp_path: Path) -> None:
    basics_path = tmp_path / "title.basics.tsv"
    basics_path.write_text(BASICS_TSV, encoding="utf-8")
    episode_path = tmp_path / "title.episode.tsv"
    episode_path.write_text(EPISODE_TSV, encoding="utf-8")

    import_basics(db, basics_path)
    written = import_episodes(db, episode_path)

    assert written == 1
    episode = TitlesRepository(db).get("tt0041039")
    assert episode is not None
    assert episode.parent_imdb_id == "tt0041038"
    assert episode.season_number == 1
    assert episode.episode_number == 9
    # import_episodes must not have touched the episode's own basics fields.
    assert episode.primary_title == "The Episode"


def test_import_basics_reports_progress_by_bytes(db: sqlite3.Connection, tmp_path: Path) -> None:
    """Progress is driven by the file's size, not a row count computed up front."""
    path = tmp_path / "title.basics.tsv"
    path.write_text(BASICS_TSV, encoding="utf-8")
    total_size = path.stat().st_size

    calls: list[tuple[int, int]] = []
    import_basics(db, path, progress=lambda current, total: calls.append((current, total)))

    # A file this small stays under the reporting threshold during the loop: the only
    # guaranteed call is the final one, which must still reach 100%.
    assert calls[-1] == (total_size, total_size)
    assert all(total == total_size for _, total in calls)


def test_import_episodes_reports_progress_by_bytes(db: sqlite3.Connection, tmp_path: Path) -> None:
    basics_path = tmp_path / "title.basics.tsv"
    basics_path.write_text(BASICS_TSV, encoding="utf-8")
    episode_path = tmp_path / "title.episode.tsv"
    episode_path.write_text(EPISODE_TSV, encoding="utf-8")
    total_size = episode_path.stat().st_size

    import_basics(db, basics_path)
    calls: list[tuple[int, int]] = []
    import_episodes(
        db, episode_path, progress=lambda current, total: calls.append((current, total))
    )

    assert calls[-1] == (total_size, total_size)


def test_import_basics_reports_progress_repeatedly_for_a_large_file(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """A file crossing several reporting thresholds gets more than one progress call."""
    header = (
        "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear"
        "\truntimeMinutes\tgenres\n"
    )
    rows = "".join(
        f"tt{index:08d}\tmovie\tTitle {index}\tTitle {index}\t0\t2000\t\\N\t90\tDrama\n"
        for index in range(60_000)
    )
    path = tmp_path / "title.basics.tsv"
    path.write_text(header + rows, encoding="utf-8")

    calls: list[tuple[int, int]] = []
    import_basics(db, path, progress=lambda current, total: calls.append((current, total)))

    assert len(calls) >= 2
    positions = [current for current, _ in calls]
    assert positions == sorted(positions)
    assert calls[-1][0] == calls[-1][1]


def test_import_basics_is_idempotent(db: sqlite3.Connection, tmp_path: Path) -> None:
    """Re-running `import-imdb` on the same file must not duplicate rows."""
    path = tmp_path / "title.basics.tsv"
    path.write_text(BASICS_TSV, encoding="utf-8")

    import_basics(db, path)
    import_basics(db, path)

    assert TitlesRepository(db).count() == 3


def test_reimporting_basics_preserves_the_episode_link(
    db: sqlite3.Connection, tmp_path: Path
) -> None:
    """A refreshed `title.basics.tsv.gz` must not silently unlink episodes.

    `import_basics` never carries parent/season/episode information: `upsert_many`
    must coalesce those columns rather than reset them to `NULL`.
    """
    basics_path = tmp_path / "title.basics.tsv"
    basics_path.write_text(BASICS_TSV, encoding="utf-8")
    episode_path = tmp_path / "title.episode.tsv"
    episode_path.write_text(EPISODE_TSV, encoding="utf-8")

    import_basics(db, basics_path)
    import_episodes(db, episode_path)
    import_basics(db, basics_path)

    episode = TitlesRepository(db).get("tt0041039")
    assert episode is not None
    assert episode.parent_imdb_id == "tt0041038"
    assert episode.season_number == 1
    assert episode.episode_number == 9


def test_import_basics_batches_across_transactions(db: sqlite3.Connection, tmp_path: Path) -> None:
    """`batch_size` splits the import into several commits, not just one."""
    header = (
        "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear"
        "\truntimeMinutes\tgenres\n"
    )
    rows = "".join(
        f"tt{index:07d}\tmovie\tTitle {index}\tTitle {index}\t0\t2000\t\\N\t90\tDrama\n"
        for index in range(5)
    )
    path = tmp_path / "title.basics.tsv"
    path.write_text(header + rows, encoding="utf-8")

    written = import_basics(db, path, batch_size=2)

    assert written == 5
    assert TitlesRepository(db).count() == 5
