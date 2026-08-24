"""Splits a subtitle into sliding chunks.

A chunk is the unit of model calls **and** the unit of resume. The overlap keeps a passage
straddling two chunks from going unnoticed.

The chunking must be **deterministic**: for a given file and a given ``(size, overlap)``,
`Chunk.index` always designates the same range of sentences. This is what makes the
``UNIQUE(run_id, file_id, chunk_index)`` constraint on the `results` table usable as an
idempotency guarantee.

STATUS: stubs, except for the value object.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from glyphwell.corpus.reader import Sentence

__all__ = ["Chunk", "chunk_count", "iter_chunks"]


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
    size: int,
    overlap: int,
    start_chunk_index: int = 0,
) -> Iterator[Chunk]:
    """Splits a stream of sentences into sliding chunks.

    Args:
        sentences: stream of sentences, consumed lazily.
        size: number of sentences per chunk.
        overlap: number of sentences repeated from one chunk to the next. Must be
            strictly less than `size`, otherwise the chunk does not advance.
        start_chunk_index: offset applied to `Chunk.index`, to number chunks correctly
            when resuming partway through a file.

    Yields:
        The successive chunks. The last one may hold fewer than `size` sentences.

    Raises:
        ValueError: `size` not strictly positive, or `overlap` outside ``[0, size)``.
    """
    raise NotImplementedError


def chunk_count(sentence_count: int, *, size: int, overlap: int) -> int:
    """Number of chunks a file of `sentence_count` sentences would produce.

    Used to display progress before the file has been read.

    Raises:
        ValueError: invalid chunking parameters.
    """
    raise NotImplementedError
