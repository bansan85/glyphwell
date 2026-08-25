"""Access to the Ollama server.

The call is exposed behind a `Protocol`: the search engine does not depend on Ollama,
and tests inject a deterministic client without running a model.

`OllamaClient.complete` only decodes the response as JSON *syntactically* when a schema
was requested — a response that isn't parseable JSON at all is a transport-level
contract violation. *Semantic* validation (schema conformance, the ``match_when`` field)
is `glyphwell.search.results.validate_output`'s job, called right after `complete`
returns. Likewise, the *policy* of which schema to request for which
``output.format`` lives in the search engine, not here: this module stays decoupled
from `glyphwell.manifest`.
"""

import functools
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

import httpx
import ollama
from pydantic import TypeAdapter, ValidationError

from glyphwell.errors import ModelOutputError, OllamaError
from glyphwell.logging import get_logger
from glyphwell.types import JsonObject, JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Completion", "LlmClient", "OllamaClient"]

_log = get_logger(__name__)

_JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)

_RETRY_BACKOFF_SECONDS: Final = (1.0, 2.0, 4.0, 8.0, 16.0)
"""Backoff between retries of a transient failure, capped for a very high `max_retries`."""


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

    def ensure_model(self, model: str) -> None:
        """Checks that a model is available before a search starts scanning the corpus."""
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
    # A reasoning-capable model (e.g. Qwen3) puts its reasoning in `message.thinking`,
    # separate from `message.content`, which `complete` reads. With reasoning left on,
    # `num_predict` can be exhausted before the model ever emits content, leaving
    # `complete` with an empty string to parse as JSON — off by default for that reason.
    think: bool = False

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
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        # `is not None`, never a truthy check: an empty-but-present schema is not "no
        # schema".
        format_arg = dict(json_schema) if json_schema is not None else None

        _log.debug("calling %s at %s (%d message(s))", model, self.host, len(messages))
        started = time.monotonic()
        response = self._chat_with_retries(
            model=model, messages=messages, options=options, format_arg=format_arg
        )
        latency_ms = round((time.monotonic() - started) * 1000)
        _log.debug("%s responded in %dms", model, latency_ms)

        text = response.message.content or ""
        payload = _decode_json_payload(text) if json_schema is not None else None
        return Completion(
            text=text, payload=payload, model=response.model or model, latency_ms=latency_ms
        )

    def _chat_with_retries(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: "Mapping[str, JsonValue] | None",
        format_arg: dict[str, JsonValue] | None,
    ) -> ollama.ChatResponse:
        """Calls `chat`, retrying transient failures with a backoff.

        A 4xx `ResponseError` (bad model, options, or schema) is fatal immediately: no
        retry can fix a request the server itself rejected as invalid.
        """
        client = _client(self.host, self.timeout)
        last_exc: Exception = OllamaError("no attempt was made")
        for attempt in range(self.max_retries):
            try:
                return client.chat(
                    model=model,
                    messages=messages,
                    options=options,
                    format=format_arg,
                    think=self.think,
                )
            except ollama.ResponseError as exc:
                if not (exc.status_code >= 500 or exc.status_code < 0):
                    message = f"Ollama rejected the request for model {model!r}: {exc}"
                    raise OllamaError(message) from exc
                last_exc = exc
            except (ConnectionError, httpx.HTTPError) as exc:
                last_exc = exc
            if attempt < self.max_retries - 1:
                backoff = _RETRY_BACKOFF_SECONDS[min(attempt, len(_RETRY_BACKOFF_SECONDS) - 1)]
                _log.warning(
                    "call to %s failed (attempt %d/%d), retrying in %.0fs: %s",
                    model,
                    attempt + 1,
                    self.max_retries,
                    backoff,
                    last_exc,
                )
                time.sleep(backoff)
        message = f"Ollama call failed after {self.max_retries} attempt(s): {last_exc}"
        raise OllamaError(message) from last_exc

    def ensure_model(self, model: str) -> None:
        """Checks that the model is available locally before starting a search.

        Failing here avoids discovering the model is missing after scanning the corpus.
        Delegates Ollama's own tag-resolution rules (for example a missing ``:latest``)
        to the server rather than reimplementing them.

        Raises:
            OllamaError: server unreachable or model not found.
        """
        _log.debug("checking model %r is available on %s", model, self.host)
        try:
            _client(self.host, self.timeout).show(model)
        except ollama.ResponseError as exc:
            message = f"model {model!r} not available on {self.host}: {exc}"
            raise OllamaError(message) from exc
        except (ConnectionError, httpx.HTTPError) as exc:
            message = f"cannot reach Ollama at {self.host}: {exc}"
            raise OllamaError(message) from exc


@functools.lru_cache(maxsize=8)
def _client(host: str, timeout: float) -> ollama.Client:
    """One `ollama.Client` per ``(host, timeout)`` pair.

    `ollama.Client` wraps an `httpx.Client`, documented thread-safe for concurrent
    requests: safe to share across the search engine's worker threads, which only ever
    call `complete` — never anything touching the database or a corpus archive handle.
    """
    return ollama.Client(host=host, timeout=timeout)


def _decode_json_payload(text: str) -> JsonObject:
    """Decodes a model response as a JSON object.

    Purely syntactic: is this parseable JSON shaped like an object? Whether it conforms
    to the manifest's schema is `glyphwell.search.results.validate_output`'s job.
    """
    try:
        return _JSON_OBJECT_ADAPTER.validate_json(text)
    except ValidationError as exc:
        message = f"model response is not valid JSON: {exc}"
        raise ModelOutputError(message) from exc
