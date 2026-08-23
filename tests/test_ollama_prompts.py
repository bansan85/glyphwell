"""Rendering of the manifest's prompt templates."""

import pytest

from glyphwell.corpus.chunker import Chunk
from glyphwell.corpus.reader import Sentence
from glyphwell.errors import ManifestError
from glyphwell.metadata.resolver import Title
from glyphwell.ollama.prompts import PLACEHOLDERS, render, render_context


def _chunk() -> Chunk:
    return Chunk(
        index=0,
        sentences=(
            Sentence(index=0, id="10", text="Hello there."),
            Sentence(index=1, id="11", text="General Kenobi."),
        ),
    )


def test_render_context_uses_the_resolved_title() -> None:
    title = Title(
        imdb_id="tt0133093",
        title_type="movie",
        primary_title="The Matrix",
        start_year=1999,
        is_adult=False,
    )
    context = render_context(chunk=_chunk(), title=title, imdb_id="tt0133093")
    assert context.title == "The Matrix (1999)"
    assert context.year == 1999
    assert context.first_id == "10"
    assert context.last_id == "11"
    assert context.chunk == "[10] Hello there.\n[11] General Kenobi."


def test_render_context_falls_back_to_the_bare_id_when_title_is_unknown() -> None:
    context = render_context(chunk=_chunk(), title=None, imdb_id="tt9999999")
    assert context.title == "tt9999999"
    assert context.year is None


def test_as_mapping_turns_a_missing_year_into_an_empty_string() -> None:
    context = render_context(chunk=_chunk(), title=None, imdb_id="tt9999999")
    assert context.as_mapping()["year"] == ""


def test_as_mapping_covers_every_known_placeholder() -> None:
    context = render_context(chunk=_chunk(), title=None, imdb_id="tt9999999")
    assert set(context.as_mapping()) == set(PLACEHOLDERS)


def test_render_substitutes_every_placeholder() -> None:
    context = render_context(chunk=_chunk(), title=None, imdb_id="tt0133093")
    template = "{{ imdb_id }} / {{ first_id }} - {{ last_id }}:\n{{ chunk }}"
    rendered = render(template, context)
    assert rendered == "tt0133093 / 10 - 11:\n[10] Hello there.\n[11] General Kenobi."


def test_render_rejects_an_unknown_placeholder() -> None:
    context = render_context(chunk=_chunk(), title=None, imdb_id="tt0133093")
    with pytest.raises(ManifestError):
        render("{{ nope }}", context)
