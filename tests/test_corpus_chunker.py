"""Token-budgeted sliding-window chunking of a subtitle's sentences."""

import pytest

from glyphwell.corpus.chunker import Chunk, iter_chunks
from glyphwell.corpus.reader import Sentence
from glyphwell.tokens import estimate_tokens


def _sentences(n: int, *, text: str = "x") -> list[Sentence]:
    """Sentences whose rendered line (`[id] text`) has the same length for every one.

    A fixed-width, zero-padded id keeps `estimate_tokens` uniform across the whole range,
    so a `token_budget` of `k * _line_weight()` reproduces the boundaries a fixed
    sentence-count window of `k` used to.
    """
    return [Sentence(index=i, id=f"{i:04d}", text=text) for i in range(n)]


def _line_weight(*, text: str = "x") -> int:
    """Estimated tokens of one line produced by `_sentences`."""
    return estimate_tokens(f"[0000] {text}")


def _windows(chunks: list[Chunk]) -> list[tuple[int, int]]:
    return [(chunk.first.index, chunk.last.index) for chunk in chunks]


def test_no_sentences_yields_no_chunks() -> None:
    assert list(iter_chunks(_sentences(0), token_budget=100, overlap=2)) == []


def test_fewer_sentences_than_budget_yields_one_chunk() -> None:
    weight = _line_weight()
    chunks = list(iter_chunks(_sentences(3), token_budget=weight * 5, overlap=2))
    assert _windows(chunks) == [(0, 2)]


def test_sliding_window_with_overlap() -> None:
    weight = _line_weight()
    chunks = list(iter_chunks(_sentences(10), token_budget=weight * 5, overlap=2))
    assert _windows(chunks) == [(0, 4), (3, 7), (6, 9)]


def test_exact_multiple_without_overlap() -> None:
    weight = _line_weight()
    chunks = list(iter_chunks(_sentences(10), token_budget=weight * 5, overlap=0))
    assert _windows(chunks) == [(0, 4), (5, 9)]


def test_trailing_partial_chunk_without_overlap() -> None:
    weight = _line_weight()
    chunks = list(iter_chunks(_sentences(11), token_budget=weight * 5, overlap=0))
    assert _windows(chunks) == [(0, 4), (5, 9), (10, 10)]


def test_start_chunk_index_offsets_every_chunk() -> None:
    weight = _line_weight()
    chunks = list(
        iter_chunks(_sentences(6), token_budget=weight * 3, overlap=0, start_chunk_index=5)
    )
    assert [chunk.index for chunk in chunks] == [5, 6]


def test_every_chunk_stays_within_budget_for_uneven_sentence_lengths() -> None:
    """The real case a fixed sentence count could never adapt to: mixed-length dialogue."""
    sentences = [
        Sentence(index=i, id=f"{i:04d}", text="x" * length)
        for i, length in enumerate([1, 50, 3, 80, 2, 2, 40, 1])
    ]
    budget = 40
    chunks = list(iter_chunks(sentences, token_budget=budget, overlap=0))

    assert sum(len(chunk.sentences) for chunk in chunks) == len(sentences)
    for chunk in chunks:
        total = sum(estimate_tokens(f"[{s.id}] {s.text}") for s in chunk.sentences)
        # A lone oversized sentence is the one allowed exception (indivisible grain).
        assert total <= budget or len(chunk.sentences) == 1


def test_a_sentence_alone_over_budget_is_still_emitted() -> None:
    sentences = [Sentence(index=0, id="0000", text="x" * 500)]
    chunks = list(iter_chunks(sentences, token_budget=10, overlap=0))
    assert len(chunks) == 1
    assert chunks[0].sentences == tuple(sentences)


def test_overlap_larger_than_a_chunk_is_clamped() -> None:
    """An overlap the buffer can't satisfy keeps whatever is available, still advancing."""
    weight = _line_weight()
    chunks = list(iter_chunks(_sentences(6), token_budget=weight * 2, overlap=10))
    assert [chunk.index for chunk in chunks]
    assert chunks[0].first.index == 0
    assert chunks[-1].last.index == 5


@pytest.mark.parametrize(("token_budget", "overlap"), [(0, 0), (-1, 0), (5, -1)])
def test_invalid_parameters_are_rejected(token_budget: int, overlap: int) -> None:
    with pytest.raises(ValueError, match=r"chunk|budget"):
        list(iter_chunks(_sentences(10), token_budget=token_budget, overlap=overlap))
