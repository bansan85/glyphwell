"""Textual prefilter applied before any call to the model.

An LLM call costs orders of magnitude more than a substring search. Across hundreds of
thousands of subtitles, locally discarding chunks that are clearly off-topic is the main
lever on the duration of a search.

The prefilter is deliberately coarse: it must never discard a chunk that the model would
have kept. When in doubt, let it through.

STATUS: stubs, outside of the value object.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from glyphwell.manifest.model import PrefilterConfig

__all__ = ["Prefilter"]


@dataclass(frozen=True, slots=True)
class Prefilter:
    """Compiled prefilter, reusable across every chunk of a search.

    Pattern compilation happens once per search, not once per chunk.
    """

    config: "PrefilterConfig"

    @classmethod
    def compile(cls, config: "PrefilterConfig") -> Self:
        """Prepares the prefilter from the manifest configuration.

        Raises:
            ManifestError: a pattern is an invalid regular expression.
        """
        raise NotImplementedError

    @property
    def enabled(self) -> bool:
        """False when the mode is ``off``: the caller can skip evaluation."""
        raise NotImplementedError

    def keeps(self, text: str) -> bool:
        """Indicates whether the chunk should be submitted to the model.

        Always returns true when the prefilter is disabled.
        """
        raise NotImplementedError
