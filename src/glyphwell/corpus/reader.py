"""Reads OPUS subtitle files in ``raw`` format.

A file contains a sequence of ``<s id="...">`` tags carrying non-tokenized text,
interspersed with ``<time>`` tags giving the timing references. Two precautions:

* reading is **incremental** (``iterparse``) and the generator frees elements as it
  goes — a subtitle can hold tens of thousands of sentences;
* files are not always well-formed, hence ``lxml`` in ``recover`` mode.

The archive is never extracted (see `glyphwell.corpus.archive`): both functions read an
already-open binary stream, obtained from `CorpusArchive.open_member`, never a `Path`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from typing import IO

from lxml import etree

from glyphwell.errors import CorpusReadError
from glyphwell.types import SentenceId

__all__ = ["Sentence", "count_sentences", "iter_sentences"]

_TIME_TAG = "time"


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


def iter_sentences(stream: IO[bytes], *, start_index: int = 0) -> Iterator[Sentence]:
    """Yields the sentences of a subtitle file, in document order.

    `start_index` allows resuming a file without reanalyzing its beginning: earlier
    sentences are traversed but not emitted. The file is re-read from the start — that is
    cheap compared to an LLM call, and it avoids depending on a byte offset that would be
    invalidated by the slightest content change.

    Args:
        stream: binary stream of a subtitle member, from `CorpusArchive.open_member`.
        start_index: first position to emit.

    Yields:
        The sentences from `start_index` onward.

    Raises:
        CorpusReadError: unreadable or unrecoverably malformed file.
    """
    position = 0
    try:
        context = etree.iterparse(stream, events=("end",), tag="s", recover=True)
        for _event, elem in context:
            if position >= start_index:
                yield _to_sentence(elem, position)
            position += 1
            _free(elem)
    except etree.XMLSyntaxError as exc:
        message = f"malformed subtitle: {exc}"
        raise CorpusReadError(message) from exc
    except OSError as exc:
        message = f"unreadable subtitle: {exc}"
        raise CorpusReadError(message) from exc


def count_sentences(stream: IO[bytes]) -> int:
    """Counts the sentences of a file, without keeping their text.

    Used to populate ``subtitle_files.sentence_count`` and to display progress.

    Raises:
        CorpusReadError: unreadable file.
    """
    count = 0
    try:
        context = etree.iterparse(stream, events=("end",), tag="s", recover=True)
        for _event, elem in context:
            count += 1
            _free(elem)
    except etree.XMLSyntaxError as exc:
        message = f"malformed subtitle: {exc}"
        raise CorpusReadError(message) from exc
    except OSError as exc:
        message = f"unreadable subtitle: {exc}"
        raise CorpusReadError(message) from exc
    return count


def _to_sentence(elem: etree._Element, position: int) -> Sentence:
    """Builds a `Sentence` from a parsed ``<s>`` element."""
    sentence_id: SentenceId = elem.get("id") or str(position)
    start: str | None = None
    end: str | None = None
    for child in elem:
        if child.tag != _TIME_TAG:
            continue
        marker = child.get("id", "")
        if marker.endswith("S"):
            start = child.get("value")
        elif marker.endswith("E"):
            end = child.get("value")
    return Sentence(index=position, id=sentence_id, text=_extract_text(elem), start=start, end=end)


def _extract_text(elem: etree._Element) -> str:
    """Gathers an ``<s>`` element's dialogue text, ``<time>`` markers excluded.

    A ``<time>`` child contributes no text of its own, but the text trailing it (between
    its closing tag and the next node) is dialogue and must be kept.
    """
    parts: list[str] = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        if child.tag != _TIME_TAG and child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)
    return " ".join(" ".join(parts).split())


def _free(elem: etree._Element) -> None:
    """Releases a parsed element and its already-visited siblings.

    Standard `lxml.etree.iterparse` idiom: without it, the tree keeps growing for the
    whole file even though only the current element is still needed.
    """
    elem.clear()
    while elem.getprevious() is not None:
        parent = elem.getparent()
        if parent is not None:
            del parent[0]
