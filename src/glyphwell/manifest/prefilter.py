"""Textual prefilter applied before any call to the model.

An LLM call costs orders of magnitude more than a substring search. Across hundreds of
thousands of subtitles, locally discarding chunks that are clearly off-topic is the main
lever on the duration of a search.

The prefilter is deliberately coarse: it must never discard a chunk that the model would
have kept. When in doubt, let it through.
"""

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self, assert_never

from glyphwell.errors import ManifestError
from glyphwell.manifest.model import PrefilterMode

if TYPE_CHECKING:
    from glyphwell.manifest.model import PrefilterConfig

__all__ = ["Prefilter"]


@dataclass(frozen=True, slots=True)
class Prefilter:
    """Compiled prefilter, reusable across every chunk of a search.

    Pattern compilation happens once per search, not once per chunk: `_patterns` holds
    the precompiled form, populated by `compile` — `slots=True` leaves no other way to
    cache it after construction.
    """

    config: "PrefilterConfig"
    _patterns: tuple[re.Pattern[str], ...] = field(default=())

    @classmethod
    def compile(cls, config: "PrefilterConfig") -> Self:
        """Prepares the prefilter from the manifest configuration.

        Every pattern is compiled into a regular expression: a literal pattern is
        `re.escape`-d first, which folds literal and regex matching into a single code
        path instead of two.

        Raises:
            ManifestError: a pattern is an invalid regular expression.
        """
        flags = 0 if config.case_sensitive else re.IGNORECASE
        compiled: list[re.Pattern[str]] = []
        for raw in config.patterns:
            source = raw if config.regex else re.escape(raw)
            try:
                compiled.append(re.compile(source, flags))
            except re.error as exc:
                message = f"invalid prefilter pattern {raw!r}: {exc}"
                raise ManifestError(message) from exc
        return cls(config=config, _patterns=tuple(compiled))

    @property
    def enabled(self) -> bool:
        """False when the mode is ``off``: the caller can skip evaluation."""
        return self.config.mode is not PrefilterMode.OFF

    def keeps(self, text: str) -> bool:
        """Indicates whether the chunk should be submitted to the model.

        Always returns true when the prefilter is disabled.
        """
        mode = self.config.mode
        if mode is PrefilterMode.ANY:
            return any(pattern.search(text) for pattern in self._patterns)
        if mode is PrefilterMode.ALL:
            return all(pattern.search(text) for pattern in self._patterns)
        if mode is PrefilterMode.NONE:
            return not any(pattern.search(text) for pattern in self._patterns)
        if mode is PrefilterMode.OFF:
            return True
        assert_never(mode)
