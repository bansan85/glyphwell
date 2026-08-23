"""Rendering of the manifest's prompt templates.

Deliberately minimal substitution — ``{{ name }}`` replaced by its value — without a full
template engine: a manifest must not be able to execute code, and a reduced syntax stays
readable in a YAML file.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from glyphwell.errors import ManifestError
from glyphwell.types import ImdbId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from glyphwell.corpus.chunker import Chunk
    from glyphwell.metadata.resolver import Title

_PLACEHOLDER_RE: Final = re.compile(r"\{\{\s*(\w+)\s*\}\}")

__all__ = ["PLACEHOLDERS", "PromptContext", "render", "render_context"]

PLACEHOLDERS: Final = (
    "title",
    "year",
    "imdb_id",
    "first_id",
    "last_id",
    "chunk",
)
"""Substitutions recognized in ``prompt.system`` and ``prompt.user``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptContext:
    """Values injected into a template for a given chunk."""

    title: str
    year: int | None
    imdb_id: ImdbId
    first_id: str
    last_id: str
    chunk: str

    def as_mapping(self) -> "Mapping[str, str]":
        """Converts the context into textual substitutions.

        Missing values become an empty string: a prompt must not contain the word
        ``None``.
        """
        return {
            "title": self.title,
            "year": "" if self.year is None else str(self.year),
            "imdb_id": self.imdb_id,
            "first_id": self.first_id,
            "last_id": self.last_id,
            "chunk": self.chunk,
        }


def render_context(*, chunk: "Chunk", title: "Title | None", imdb_id: ImdbId) -> PromptContext:
    """Assembles the context for a chunk.

    `title` can be `None` when the IMDb datasets do not know the identifier: the label
    then falls back to the identifier itself, and the search continues.
    """
    return PromptContext(
        title=title.display_name() if title is not None else imdb_id,
        year=title.start_year if title is not None else None,
        imdb_id=imdb_id,
        first_id=chunk.first.id,
        last_id=chunk.last.id,
        chunk=chunk.render(with_ids=True),
    )


def render(template: str, context: PromptContext) -> str:
    """Substitutes the ``{{ placeholders }}`` of a template.

    Args:
        template: template taken from the manifest.
        context: values for the current chunk.

    Returns:
        The prompt ready to be sent.

    Raises:
        ManifestError: the template references an unknown placeholder — better to report
            it than to send a truncated prompt to thousands of chunks.
    """
    mapping = context.as_mapping()

    def _substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in mapping:
            known = ", ".join(PLACEHOLDERS)
            message = f"unknown placeholder {{{{ {name} }}}} in prompt template (known: {known})"
            raise ManifestError(message)
        return mapping[name]

    return _PLACEHOLDER_RE.sub(_substitute, template)
