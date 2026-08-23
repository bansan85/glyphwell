"""Streaming reader for OPUS raw-format subtitle XML."""

from pathlib import Path

import pytest

from glyphwell.corpus.archive import CorpusArchive
from glyphwell.corpus.reader import count_sentences, iter_sentences
from glyphwell.errors import CorpusReadError

SUBTITLE_MEMBER = "OpenSubtitles/raw/en/1999/0133093/3660124.xml"


def test_iter_sentences_reads_text_ids_and_times(sample_subtitle: Path) -> None:
    with sample_subtitle.open("rb") as stream:
        sentences = list(iter_sentences(stream))

    assert [sentence.index for sentence in sentences] == [0, 1, 2]
    assert [sentence.id for sentence in sentences] == ["1", "2", "3"]
    assert sentences[0].text == "First placeholder line of dialogue."
    assert sentences[1].text == "Second placeholder line, same scene."
    assert sentences[2].text == "Third placeholder line, next scene."
    assert sentences[0].start == "00:00:314"
    assert sentences[0].end is None
    assert sentences[1].end == "00:02:118"
    assert sentences[2].start == "00:04:002"


def test_iter_sentences_start_index_skips_without_renumbering(sample_subtitle: Path) -> None:
    with sample_subtitle.open("rb") as stream:
        sentences = list(iter_sentences(stream, start_index=1))
    assert [sentence.index for sentence in sentences] == [1, 2]
    assert sentences[0].text == "Second placeholder line, same scene."


def test_count_sentences(sample_subtitle: Path) -> None:
    with sample_subtitle.open("rb") as stream:
        assert count_sentences(stream) == 3


def test_reads_from_the_archive_via_open_member(sample_archive: Path) -> None:
    with (
        CorpusArchive(sample_archive) as archive,
        archive.open_member(SUBTITLE_MEMBER) as stream,
    ):
        sentences = list(iter_sentences(stream))
    assert len(sentences) == 3


def test_missing_id_falls_back_to_position(tmp_path: Path) -> None:
    path = tmp_path / "no-id.xml"
    path.write_bytes(b"<document><s>hello</s></document>")
    with path.open("rb") as stream:
        sentences = list(iter_sentences(stream))
    assert sentences[0].id == "0"
    assert sentences[0].text == "hello"


def test_recovers_from_an_unterminated_document(tmp_path: Path) -> None:
    path = tmp_path / "broken.xml"
    path.write_bytes(b'<document><s id="1">hello</s>')
    with path.open("rb") as stream:
        sentences = list(iter_sentences(stream))
    assert [sentence.text for sentence in sentences] == ["hello"]
    assert sentences[0].id == "1"


def test_empty_stream_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "empty.xml"
    path.write_bytes(b"")
    with path.open("rb") as stream, pytest.raises(CorpusReadError):
        list(iter_sentences(stream))


def test_garbage_stream_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "garbage.xml"
    path.write_bytes(b"\x00\x01\x02binary garbage")
    with path.open("rb") as stream, pytest.raises(CorpusReadError):
        list(iter_sentences(stream))
