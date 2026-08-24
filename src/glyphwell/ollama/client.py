"""Access to the Ollama server.

The call is exposed behind a `Protocol`: the search engine does not depend on Ollama,
and tests inject a deterministic client without running a model.

STATUS: stubs, apart from the value object.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from glyphwell.types import JsonObject, JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Completion", "LlmClient", "OllamaClient"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Completion:
    """Model response for a chunk.

    Attributes:
        text: raw response, kept as-is for diagnostics.
        payload: response decoded and validated against the manifest's schema, or `None`
            for text output.
        model: model that actually answered, as reported by the server.
        latency_ms: call duration, useful to estimate the remainder of a search.
    """

    text: str
    payload: JsonObject | None
    model: str
    latency_ms: int


class LlmClient(Protocol):
    """Minimal contract expected by the search engine."""

    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: "Mapping[str, JsonValue] | None" = None,
        json_schema: "Mapping[str, JsonValue] | None" = None,
    ) -> Completion:
        """Submits a chunk to the model and returns its response."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaClient:
    """`LlmClient` backed by the Ollama server.

    `json_schema` is passed to the server to constrain generation, then the response is
    **re-checked client-side**: the constraint reduces deviations, it does not eliminate
    them.
    """

    host: str = "http://localhost:11434"
    timeout: float = 300.0
    max_retries: int = 3

    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: "Mapping[str, JsonValue] | None" = None,
        json_schema: "Mapping[str, JsonValue] | None" = None,
    ) -> Completion:
        """See `LlmClient.complete`.

        Raises:
            OllamaError: server unreachable, model missing, or failure after `max_retries`.
            ModelOutputError: response does not conform to the requested schema.
        """
        raise NotImplementedError

    def ensure_model(self, model: str) -> None:
        """Checks that the model is available locally before starting a search.

        Failing here avoids discovering the model is missing after scanning the corpus.

        Raises:
            OllamaError: server unreachable or model not found.
        """
        raise NotImplementedError
