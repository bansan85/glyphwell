"""Splits a subtitle into sliding chunks.

A chunk is the unit of model calls **and** the unit of resume. The overlap keeps a passage
straddling two chunks from going unnoticed.

The chunking must be **deterministic**: for a given file and a given
``(token_budget, overlap)``, `Chunk.index` always designates the same range of sentences.
This is what makes the ``UNIQUE(run_id, file_id, chunk_index)`` constraint on the `results`
table usable as an idempotency guarantee. `token_budget` is derived, once per file, from
`options.num_ctx`/`options.num_predict` and the rendered prompt overhead — see
`glyphwell.tokens` — so it is as deterministic per manifest as a hardcoded sentence count
used to be.
"""

from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

from glyphwell.logging import get_logger
from glyphwell.tokens import estimate_tokens

if TYPE_CHECKING:
    from glyphwell.corpus.reader import Sentence

__all__ = ["Chunk", "iter_chunks"]

_log = get_logger(__name__)


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk:
    """A chunk of consecutive sentences.

    Attributes:
        index: position of the chunk in the file, starting at 0.
        sentences: the sentences of the chunk, in order. Never empty.
    """

    index: int
    sentences: tuple["Sentence", ...]

    @property
    def first(self) -> "Sentence":
        """First sentence of the chunk."""
        return self.sentences[0]

    @property
    def last(self) -> "Sentence":
        """Last sentence of the chunk. Determines the resume cursor's progress."""
        return self.sentences[-1]

    def render(self, *, with_ids: bool = True) -> str:
        """Assembles the chunk's text for injection into the prompt.

        Args:
            with_ids: prefixes each line with its sentence identifier, which lets the
                model cite verifiable references.
        """
        if with_ids:
            return "\n".join(f"[{sentence.id}] {sentence.text}" for sentence in self.sentences)
        return "\n".join(sentence.text for sentence in self.sentences)


def iter_chunks(
    sentences: Iterable["Sentence"],
    *,
    token_budget: int,
    overlap: int,
    start_chunk_index: int = 0,
) -> Iterator[Chunk]:
    """Splits a stream of sentences into sliding, token-budgeted chunks.

    Args:
        sentences: stream of sentences, consumed lazily.
        token_budget: maximum estimated tokens (see `glyphwell.tokens.estimate_tokens`)
            of a chunk's rendered sentences, in `Chunk.render(with_ids=True)`'s form.
        overlap: number of sentences repeated from one chunk to the next, so a passage
            straddling the boundary is not analyzed only once. Clamped down to a chunk's
            own sentence count when it holds fewer sentences than `overlap`.
        start_chunk_index: offset applied to `Chunk.index`, to number chunks correctly
            when resuming partway through a file.

    Yields:
        The successive chunks. A single sentence whose own estimate exceeds
        `token_budget` is still yielded alone — the sentence is the indivisible grain,
        so this is the best this function can do; it logs a warning when it happens.

    Raises:
        ValueError: `token_budget` not strictly positive, or `overlap` negative.
    """
    _validate(token_budget, overlap)
    buffer: deque[tuple[Sentence, int]] = deque()
    buffered_tokens = 0
    chunk_index = start_chunk_index
    for sentence in sentences:
        weight = _line_tokens(sentence)
        if weight > token_budget:
            _log.warning(
                "sentence %s alone (~%d estimated tokens) exceeds the token budget (%d):"
                " emitting it as an oversized chunk",
                sentence.id,
                weight,
                token_budget,
            )
        if buffer and buffered_tokens + weight > token_budget:
            yield Chunk(index=chunk_index, sentences=tuple(s for s, _ in buffer))
            chunk_index += 1
            while len(buffer) > overlap:
                _, popped_weight = buffer.popleft()
                buffered_tokens -= popped_weight
        buffer.append((sentence, weight))
        buffered_tokens += weight
    if buffer:
        yield Chunk(index=chunk_index, sentences=tuple(s for s, _ in buffer))


def _line_tokens(sentence: "Sentence") -> int:
    """Estimated tokens of a sentence as rendered in a prompt, `Chunk.render`'s form."""
    return estimate_tokens(f"[{sentence.id}] {sentence.text}")


def _validate(token_budget: int, overlap: int) -> None:
    """Shared bounds check for `iter_chunks`."""
    if token_budget < 1:
        message = f"token budget must be >= 1, got {token_budget}"
        raise ValueError(message)
    if overlap < 0:
        message = f"chunk overlap must be >= 0, got {overlap}"
        raise ValueError(message)
