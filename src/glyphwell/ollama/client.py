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

A response that fails the syntactic JSON check is, in practice, almost always one Ollama
cut off mid-generation because `num_predict` ran out before the model finished — chunk
sizing (ADR-0021/ADR-0022) makes this rare, not impossible; see ADR-0022's own *Risks*
section. `complete` retries such a response with a larger `num_predict` before giving up
(`max_output_retries`), rather than surfacing `ModelOutputError` on the first truncation
and costing the whole file (`search/engine.py` marks a file in error on any `OllamaError`,
which `ModelOutputError` is a subclass of).
"""

import functools
import math
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

_OUTPUT_RETRY_NUM_PREDICT_GROWTH: Final = 1.5
"""Growth factor applied to `num_predict` on each retry of a truncated JSON response.

Capped so the retry never asks for more than `num_ctx` leaves room for once the prompt
itself is accounted for (see `_widen_num_predict`) — otherwise a large enough retry would
start truncating the *prompt* instead of the response, trading one truncation for a worse
one."""


@dataclass(frozen=True, slots=True, kw_only=True)
class Completion:
    """Model response for a chunk.

    Attributes:
        text: raw response, kept as-is for diagnostics.
        payload: response decoded and validated against the manifest's schema, or `None`
            for text output.
        model: model that actually answered, as reported by the server.
        latency_ms: call duration, useful to estimate the remainder of a search.
        prompt_tokens: tokens the server counted in the rendered prompt (Ollama's
            `prompt_eval_count`), `None` if the server's response omitted it.
        completion_tokens: tokens the server generated for the response (Ollama's
            `eval_count`), `None` if the server's response omitted it.
    """

    text: str
    payload: JsonObject | None
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


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
    max_output_retries: int = 3
    """Total attempts (the first plus retries) at getting a syntactically valid JSON
    response out of one chat call, each retry raised `num_predict` by
    `_OUTPUT_RETRY_NUM_PREDICT_GROWTH`. Only consulted when a schema was requested — text
    output is never decoded, so nothing here applies to it."""
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
            ModelOutputError: response still does not parse as JSON after
                `max_output_retries` attempts, each with a larger `num_predict`.
        """
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        # `is not None`, never a truthy check: an empty-but-present schema is not "no
        # schema".
        format_arg = dict(json_schema) if json_schema is not None else None
        call_options: dict[str, JsonValue] = dict(options) if options is not None else {}

        started = time.monotonic()
        response = self._chat_with_retries(
            model=model, messages=messages, options=call_options, format_arg=format_arg
        )
        text = response.message.content or ""
        payload: JsonObject | None = None
        if json_schema is not None:
            payload, text, response = self._decode_with_retries(
                text,
                response=response,
                model=model,
                messages=messages,
                options=call_options,
                format_arg=format_arg,
            )
        latency_ms = round((time.monotonic() - started) * 1000)
        return Completion(
            text=text,
            payload=payload,
            model=response.model or model,
            latency_ms=latency_ms,
            prompt_tokens=response.prompt_eval_count,
            completion_tokens=response.eval_count,
        )

    def _decode_with_retries(
        self,
        text: str,
        *,
        response: "ollama.ChatResponse",
        model: str,
        messages: list[dict[str, str]],
        options: dict[str, JsonValue],
        format_arg: dict[str, JsonValue] | None,
    ) -> tuple[JsonObject, str, "ollama.ChatResponse"]:
        """Decodes `text` as JSON, retrying with a larger `num_predict` on failure.

        See the module docstring for why a decode failure is treated as retryable rather
        than immediately fatal. `max(1, ...)` so a misconfigured `max_output_retries <= 0`
        still gets exactly one decode attempt instead of silently skipping it.
        """
        last_exc: ModelOutputError = ModelOutputError("no attempt was made")
        for attempt in range(max(1, self.max_output_retries)):
            try:
                return _decode_json_payload(text), text, response
            except ModelOutputError as exc:
                last_exc = exc
                if attempt >= self.max_output_retries - 1:
                    break
                options = _widen_num_predict(options, prompt_tokens=response.prompt_eval_count)
                _log.warning(
                    "response for %s was not valid JSON (attempt %d/%d), retrying with"
                    " num_predict=%s: %s",
                    model,
                    attempt + 1,
                    self.max_output_retries,
                    options.get("num_predict"),
                    exc,
                )
                response = self._chat_with_retries(
                    model=model, messages=messages, options=options, format_arg=format_arg
                )
                text = response.message.content or ""
        raise last_exc

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


def _widen_num_predict(
    options: "Mapping[str, JsonValue]", *, prompt_tokens: int | None
) -> dict[str, JsonValue]:
    """Returns `options` with `num_predict` grown by `_OUTPUT_RETRY_NUM_PREDICT_GROWTH`.

    Capped at what's left of `num_ctx` once the prompt itself is accounted for —
    `prompt_tokens`, the just-failed attempt's own `prompt_eval_count`, is a real
    measurement, not an estimate, so this is exact rather than conservative. Falls back
    to capping at `num_ctx` alone if the server didn't report `prompt_eval_count`, and
    never shrinks `num_predict` below its current value even if that leaves no headroom
    — the caller then simply retries identically, which a chat call is not guaranteed to
    answer the same way twice.

    Silently returns `options` unchanged if `num_predict`/`num_ctx` aren't plain,
    non-bool ints: `SearchManifest` already validates them as such before a search ever
    calls in here (see this module's docstring on staying decoupled from
    `glyphwell.manifest`), but nothing stops a caller from handing this client an
    untyped options mapping directly.
    """
    widened = dict(options)
    num_predict = widened.get("num_predict")
    if not isinstance(num_predict, int) or isinstance(num_predict, bool):
        return widened
    grown = math.ceil(num_predict * _OUTPUT_RETRY_NUM_PREDICT_GROWTH)
    num_ctx = widened.get("num_ctx")
    if isinstance(num_ctx, int) and not isinstance(num_ctx, bool):
        room = num_ctx - prompt_tokens if prompt_tokens is not None else num_ctx
        grown = max(num_predict, min(grown, room))
    widened["num_predict"] = grown
    return widened


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
