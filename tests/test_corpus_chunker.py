"""Sliding-window chunking of a subtitle's sentences."""

import pytest

from glyphwell.corpus.chunker import Chunk, chunk_count, iter_chunks
from glyphwell.corpus.reader import Sentence


def _sentences(n: int) -> list[Sentence]:
    return [Sentence(index=i, id=str(i), text=f"s{i}") for i in range(n)]


def _windows(chunks: list[Chunk]) -> list[tuple[int, int]]:
    return [(chunk.first.index, chunk.last.index) for chunk in chunks]


def test_no_sentences_yields_no_chunks() -> None:
    assert list(iter_chunks(_sentences(0), size=5, overlap=2)) == []
    assert chunk_count(0, size=5, overlap=2) == 0


def test_fewer_sentences_than_size_yields_one_chunk() -> None:
    chunks = list(iter_chunks(_sentences(3), size=5, overlap=2))
    assert _windows(chunks) == [(0, 2)]
    assert chunk_count(3, size=5, overlap=2) == 1


def test_sliding_window_with_overlap() -> None:
    chunks = list(iter_chunks(_sentences(10), size=5, overlap=2))
    assert _windows(chunks) == [(0, 4), (3, 7), (6, 9)]
    assert chunk_count(10, size=5, overlap=2) == 3


def test_exact_multiple_without_overlap() -> None:
    chunks = list(iter_chunks(_sentences(10), size=5, overlap=0))
    assert _windows(chunks) == [(0, 4), (5, 9)]
    assert chunk_count(10, size=5, overlap=0) == 2


def test_trailing_partial_chunk_without_overlap() -> None:
    chunks = list(iter_chunks(_sentences(11), size=5, overlap=0))
    assert _windows(chunks) == [(0, 4), (5, 9), (10, 10)]
    assert chunk_count(11, size=5, overlap=0) == 3


def test_start_chunk_index_offsets_every_chunk() -> None:
    chunks = list(iter_chunks(_sentences(6), size=3, overlap=0, start_chunk_index=5))
    assert [chunk.index for chunk in chunks] == [5, 6]


@pytest.mark.parametrize(
    ("n", "size", "overlap"),
    [(10, 5, 2), (10, 5, 0), (11, 5, 0), (3, 5, 2), (0, 5, 2), (37, 8, 3)],
)
def test_chunk_count_matches_iter_chunks(n: int, size: int, overlap: int) -> None:
    chunks = list(iter_chunks(_sentences(n), size=size, overlap=overlap))
    assert len(chunks) == chunk_count(n, size=size, overlap=overlap)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    if chunks:
        assert chunks[0].first.index == 0
        assert chunks[-1].last.index == n - 1


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (-1, 0), (5, 5), (5, 6), (5, -1)])
def test_invalid_parameters_are_rejected(size: int, overlap: int) -> None:
    with pytest.raises(ValueError, match="chunk"):
        list(iter_chunks(_sentences(10), size=size, overlap=overlap))
    with pytest.raises(ValueError, match="chunk"):
        chunk_count(10, size=size, overlap=overlap)
