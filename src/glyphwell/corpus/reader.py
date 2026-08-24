"""Reads OPUS subtitle files in ``raw`` format.

A file contains a sequence of ``<s id="...">`` tags carrying non-tokenized text,
interspersed with ``<time>`` tags giving the timing references. Two precautions:

* reading is **incremental** (``iterparse``) and the generator frees elements as it
  goes — a subtitle can hold tens of thousands of sentences;
* files are not always well-formed, hence ``lxml`` in ``recover`` mode.

STATUS: stubs, except for the value object.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from glyphwell.types import SentenceId

__all__ = ["Sentence", "count_sentences", "iter_sentences"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Sentence:
    """A sentence of the subtitle.

    Attributes:
        index: position in the stream, starting at 0. **Authoritative for resume**:
            unlike `id`, it is always contiguous and comparable.
        id: ``id`` attribute of the ``<s>`` tag, kept for traceability. Opaque: ordered,
            but not necessarily contiguous nor purely numeric.
        text: text of the sentence, whitespace normalized.
        start: nearest entry timestamp (``<time value="...">``), if known.
        end: nearest exit timestamp, if known.
    """

    index: int
    id: SentenceId
    text: str
    start: str | None = None
    end: str | None = None


def iter_sentences(path: Path, *, start_index: int = 0) -> Iterator[Sentence]:
    """Yields the sentences of a subtitle file, in document order.

    `start_index` allows resuming a file without reanalyzing its beginning: earlier
    sentences are traversed but not emitted. The file is re-read from the start — that is
    cheap compared to an LLM call, and it avoids depending on a byte offset that would be
    invalidated by the slightest content change.

    Args:
        path: ``.xml`` or ``.xml.gz`` file of the corpus.
        start_index: first position to emit.

    Yields:
        The sentences from `start_index` onward.

    Raises:
        CorpusReadError: unreadable or unrecoverably malformed file.
    """
    raise NotImplementedError


def count_sentences(path: Path) -> int:
    """Counts the sentences of a file, without keeping their text.

    Used to populate ``subtitle_files.sentence_count`` and to display progress.

    Raises:
        CorpusReadError: unreadable file.
    """
    raise NotImplementedError
