"""`OllamaClient`'s retry behavior, against a scripted fake `ollama.Client` — never a real
Ollama server.

Covers the response-decode retry only (`_decode_with_retries`/`_widen_num_predict`):
`_chat_with_retries`'s transient-failure backoff predates this file and isn't retested
here.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field

import pytest

from glyphwell.errors import ModelOutputError
from glyphwell.ollama import client as client_module
from glyphwell.ollama.client import OllamaClient
from glyphwell.types import JsonValue


@dataclass(frozen=True, slots=True)
class _FakeMessage:
    content: str


@dataclass(frozen=True, slots=True)
class _FakeChatResponse:
    message: _FakeMessage
    model: str = "fake-model"
    prompt_eval_count: int | None = 100
    eval_count: int | None = 50


@dataclass(slots=True)
class _ScriptedChat:
    """Fake Ollama client: returns one scripted response per call, in call order."""

    responses: list[_FakeChatResponse]
    options_seen: list[Mapping[str, JsonValue] | None] = field(default_factory=list)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        options: Mapping[str, JsonValue] | None,
        format: dict[str, JsonValue] | None,
        think: bool,
    ) -> _FakeChatResponse:
        self.options_seen.append(options)
        return self.responses.pop(0)


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: _ScriptedChat) -> None:
    monkeypatch.setattr(client_module, "_client", lambda _host, _timeout: fake)


def test_complete_retries_truncated_json_with_larger_num_predict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _ScriptedChat(
        responses=[
            _FakeChatResponse(message=_FakeMessage(content='{"matched": true, "fin')),
            _FakeChatResponse(message=_FakeMessage(content='{"matched": true}')),
        ]
    )
    _patch_client(monkeypatch, fake)

    result = OllamaClient(max_output_retries=3).complete(
        model="m",
        user="u",
        options={"num_ctx": 4096, "num_predict": 100},
        json_schema={"type": "object"},
    )

    assert result.payload == {"matched": True}
    assert len(fake.options_seen) == 2
    retry_options = fake.options_seen[1]
    assert retry_options is not None
    assert retry_options["num_predict"] == 150  # ceil(100 * 1.5)


def test_complete_raises_after_exhausting_output_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    broken = _FakeChatResponse(message=_FakeMessage(content="not json"))
    fake = _ScriptedChat(responses=[broken, broken, broken])
    _patch_client(monkeypatch, fake)

    with pytest.raises(ModelOutputError):
        OllamaClient(max_output_retries=3).complete(
            model="m",
            user="u",
            options={"num_ctx": 4096, "num_predict": 100},
            json_schema={"type": "object"},
        )

    assert len(fake.options_seen) == 3


def test_complete_num_predict_growth_never_shrinks_below_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`num_ctx` leaves almost no headroom once the prompt is accounted for: the retry
    keeps `num_predict` unchanged rather than shrinking it below its current value."""
    fake = _ScriptedChat(
        responses=[
            _FakeChatResponse(message=_FakeMessage(content="broken"), prompt_eval_count=3900),
            _FakeChatResponse(
                message=_FakeMessage(content='{"matched": false}'), prompt_eval_count=3900
            ),
        ]
    )
    _patch_client(monkeypatch, fake)

    OllamaClient(max_output_retries=2).complete(
        model="m",
        user="u",
        options={"num_ctx": 4096, "num_predict": 3000},
        json_schema={"type": "object"},
    )

    retry_options = fake.options_seen[1]
    assert retry_options is not None
    assert retry_options["num_predict"] == 3000


def test_complete_does_not_retry_text_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """No `json_schema`: an unparseable body is never even attempted as JSON."""
    fake = _ScriptedChat(
        responses=[_FakeChatResponse(message=_FakeMessage(content="not json at all"))]
    )
    _patch_client(monkeypatch, fake)

    result = OllamaClient(max_output_retries=3).complete(model="m", user="u")

    assert result.payload is None
    assert result.text == "not json at all"
    assert len(fake.options_seen) == 1
