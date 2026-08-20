"""Search manifest model.

A manifest is a declarative YAML: prompt, Ollama model, selection filters, chunking
parameters, textual prefilter, and expected output schema. It is validated by pydantic at
load time, which makes a poorly described search fail before the first call to the model
rather than at the thousandth file.

No code is ever executed from a manifest: it is data, versionable, diffable, and
hashable.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "ChunkConfig",
    "OutputConfig",
    "OutputFormat",
    "PrefilterConfig",
    "PrefilterMode",
    "PromptConfig",
    "SearchManifest",
    "SelectConfig",
    "YearRange",
]

type OutputFormat = Literal["json", "text"]


class _Base(BaseModel):
    """Common base: an unknown field is an error, not silence.

    A typo in a YAML key must not turn into a filter that is silently ignored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class PrefilterMode(StrEnum):
    """Prefiltering mode applied before any call to the model."""

    ANY = "any"
    """Keep the chunk if at least one pattern is present."""

    ALL = "all"
    """Keep the chunk if all patterns are present."""

    NONE = "none"
    """Keep the chunk if no pattern is present."""

    OFF = "off"
    """No prefiltering: every chunk is sent to the model."""


class ChunkConfig(_Base):
    """Chunking: unit of model calls and unit of resuming."""

    size: int = Field(default=80, ge=1, description="Number of sentences per chunk.")
    overlap: int = Field(
        default=10,
        ge=0,
        description=(
            "Sentences repeated from one chunk to the next, so a passage is not cut in two."
        ),
    )

    @model_validator(mode="after")
    def _check_overlap(self) -> Self:
        """An overlap greater than or equal to the size would prevent the chunk from advancing."""
        if self.overlap >= self.size:
            message = f"chunk.overlap ({self.overlap}) must be < chunk.size ({self.size})"
            raise ValueError(message)
        return self


class PrefilterConfig(_Base):
    """Textual prefilter, evaluated locally.

    An LLM call costs orders of magnitude more than a substring search: across hundreds
    of thousands of subtitles, a well-chosen prefilter changes the total duration of a
    search.
    """

    mode: PrefilterMode = PrefilterMode.OFF
    patterns: tuple[str, ...] = ()
    case_sensitive: bool = False
    regex: bool = Field(
        default=False,
        description="Interpret the patterns as regular expressions.",
    )

    @model_validator(mode="after")
    def _check_patterns(self) -> Self:
        """An active mode without a pattern would filter nothing, or everything: an input error."""
        if self.mode is not PrefilterMode.OFF and not self.patterns:
            message = f"prefilter.mode = {self.mode.value} requires at least one pattern"
            raise ValueError(message)
        return self


class YearRange(_Base):
    """Year range, bounds included. `None` means "no bound"."""

    min: int | None = None
    max: int | None = None

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        """Reversed bounds: more likely a mistake than an intent."""
        if self.min is not None and self.max is not None and self.min > self.max:
            message = f"select.years.min ({self.min}) > select.years.max ({self.max})"
            raise ValueError(message)
        return self


class SelectConfig(_Base):
    """Selection of subtitles to analyze.

    Filters on the title (type, year, adult content) require the IMDb datasets to have
    been imported; without them, unresolved files are excluded.
    """

    languages: tuple[str, ...] = ("en",)
    title_types: tuple[str, ...] = Field(
        default=(),
        description="IMDb types kept (movie, tvEpisode, tvSeries...). Empty = all.",
    )
    years: YearRange = YearRange()
    exclude_adult: bool = True
    imdb_ids: tuple[str, ...] | None = Field(
        default=None,
        description="Restricts the search to these titles. `null` = the whole corpus.",
    )


class PromptConfig(_Base):
    """Prompt templates.

    Available substitutions: ``{{ title }}``, ``{{ year }}``, ``{{ imdb_id }}``,
    ``{{ first_id }}``, ``{{ last_id }}``, ``{{ chunk }}``.
    """

    system: str | None = None
    user: str = Field(min_length=1)


class OutputConfig(_Base):
    """Expected shape of the model's response."""

    format: OutputFormat = "json"
    json_schema: dict[str, JsonValue] | None = Field(
        default=None,
        alias="schema",
        description=(
            "JSON Schema passed to Ollama to constrain generation, then re-checked client-side."
        ),
    )

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _check_schema(self) -> Self:
        """A schema only makes sense for JSON output."""
        if self.format == "text" and self.json_schema is not None:
            message = "output.schema cannot be used with output.format = text"
            raise ValueError(message)
        return self


class SearchManifest(_Base):
    """A complete search manifest."""

    name: str = Field(min_length=1, description="Human-readable identifier of the search.")
    description: str | None = None
    model: str = Field(min_length=1, description="Ollama model, for example llama3.1:8b.")
    options: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Options passed through as-is to Ollama (temperature, num_ctx...).",
    )

    select: SelectConfig = SelectConfig()
    chunk: ChunkConfig = ChunkConfig()
    prefilter: PrefilterConfig = PrefilterConfig()
    prompt: PromptConfig
    output: OutputConfig = OutputConfig()

    match_when: str | None = Field(
        default=None,
        description=(
            "Name of the boolean field of the response that determines `results.matched`. "
            "`null`: every produced result is considered a match."
        ),
    )
