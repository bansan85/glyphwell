"""Parsing of OPUS archive member names."""

import os
import zipfile
from pathlib import Path

import pytest

from glyphwell.corpus.archive import CorpusArchive
from glyphwell.corpus.layout import CorpusEntry, iter_corpus, normalize_imdb_id, parse_entry
from glyphwell.errors import CorpusLayoutError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("133093", "tt0133093"),
        ("1596342", "tt1596342"),
        ("tt0133093", "tt0133093"),
        ("tt133093", "tt0133093"),
        ("  0133093  ", "tt0133093"),
    ],
)
def test_normalize_imdb_id_accepts_every_known_shape(raw: str, expected: str) -> None:
    assert normalize_imdb_id(raw) == expected


@pytest.mark.parametrize("raw", ["", "tt", "abc", "12a34", "tt-1"])
def test_normalize_imdb_id_rejects_garbage(raw: str) -> None:
    with pytest.raises(CorpusLayoutError):
        normalize_imdb_id(raw)


def test_parse_entry_reads_the_documented_example() -> None:
    entry = parse_entry(Path("OpenSubtitles/raw/fr/2022/1596342/1957893755.xml"))
    assert entry == CorpusEntry(
        rel_path="OpenSubtitles/raw/fr/2022/1596342/1957893755.xml",
        language="fr",
        year=2022,
        imdb_id="tt1596342",
        opensubtitles_file_id="1957893755",
    )


@pytest.mark.skipif(os.name != "nt", reason="exercises Windows-style backslash separators")
def test_parse_entry_normalizes_windows_separators() -> None:
    """`rel_path` must stay `/`-joined: it is `CorpusArchive.open_member`'s only key."""
    entry = parse_entry(Path("OpenSubtitles\\raw\\en\\1999\\0133093\\3660124.xml"))
    assert entry.rel_path == "OpenSubtitles/raw/en/1999/0133093/3660124.xml"


def test_parse_entry_tolerates_a_non_numeric_year_directory() -> None:
    entry = parse_entry(Path("OpenSubtitles/raw/en/unknown/0133093/3660124.xml"))
    assert entry.year is None
    assert entry.imdb_id == "tt0133093"


@pytest.mark.parametrize(
    "rel_path",
    [
        "raw/en/1999/0133093/3660124.xml",  # too few segments
        "extra/OpenSubtitles/raw/en/1999/0133093/3660124.xml",  # too many segments
        "OpenSubtitles/raw/en/1999/0133093/3660124.xml.gz",  # wrong suffix
        "OpenSubtitles/raw/en/1999/notanumber/3660124.xml",  # unparsable imdb id
    ],
)
def test_parse_entry_rejects_unexpected_shapes(rel_path: str) -> None:
    with pytest.raises(CorpusLayoutError):
        parse_entry(Path(rel_path))


def test_iter_corpus_skips_unparsable_members_and_filters_by_language(tmp_path: Path) -> None:
    path = tmp_path / "mixed.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("OpenSubtitles/raw/en/1999/0133093/3660124.xml", "<document/>")
        archive.writestr("OpenSubtitles/raw/fr/2022/1596342/1957893755.xml", "<document/>")
        archive.writestr("bad/shape.xml", "<document/>")

    with CorpusArchive(path) as corpus_archive:
        all_entries = list(iter_corpus(corpus_archive))
        en_entries = list(iter_corpus(corpus_archive, language="en"))

    assert {entry.rel_path for entry in all_entries} == {
        "OpenSubtitles/raw/en/1999/0133093/3660124.xml",
        "OpenSubtitles/raw/fr/2022/1596342/1957893755.xml",
    }
    assert [entry.rel_path for entry in en_entries] == [
        "OpenSubtitles/raw/en/1999/0133093/3660124.xml"
    ]
