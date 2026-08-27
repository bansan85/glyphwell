"""Token-count estimation and chunk token budgeting."""

import math

import pytest

from glyphwell.errors import ManifestError
from glyphwell.tokens import (
    CHARS_PER_TOKEN,
    SAFETY_MARGIN_RATIO,
    chunk_token_budget,
    estimate_tokens,
)


def test_estimate_tokens_of_empty_text_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_rounds_up() -> None:
    text = "x" * 10
    assert estimate_tokens(text) == math.ceil(10 / CHARS_PER_TOKEN)


def test_estimate_tokens_scales_with_length() -> None:
    assert estimate_tokens("x" * 100) > estimate_tokens("x" * 10)


def test_chunk_token_budget_is_bounded_by_the_context_ceiling() -> None:
    """`num_predict` is set generously above the expected ceiling so the context-derived
    ceiling — num_ctx minus num_predict, overhead, and margin — is the binding constraint,
    not the num_predict cap exercised separately below."""
    num_ctx = 1000
    num_predict = 700
    overhead_text = "x" * 32  # estimate_tokens("x" * 32) tokens
    budget = chunk_token_budget(
        num_ctx=num_ctx, num_predict=num_predict, overhead_text=overhead_text
    )
    expected_margin = math.ceil(SAFETY_MARGIN_RATIO * num_ctx)
    expected_ceiling = num_ctx - num_predict - estimate_tokens(overhead_text) - expected_margin
    assert budget == expected_ceiling
    assert budget > 0


def test_chunk_token_budget_is_capped_at_num_predict() -> None:
    """A chunk far larger than the response budget guarantees a truncated response for
    any task whose output scales with its input (one finding described per interesting
    line, say): Ollama stops generating exactly at num_predict, mid-JSON. The chunk must
    therefore never be allowed to dwarf num_predict just because num_ctx has the room."""
    budget = chunk_token_budget(num_ctx=24576, num_predict=1024, overhead_text="short overhead")
    assert budget == 1024


def test_chunk_token_budget_raises_when_num_ctx_cannot_cover_the_rest() -> None:
    with pytest.raises(ManifestError, match="num_ctx"):
        chunk_token_budget(num_ctx=100, num_predict=90, overhead_text="x" * 200)


def test_chunk_token_budget_margin_scales_with_num_ctx() -> None:
    """A flat token count would under-margin a huge num_ctx and over-margin a tiny one.

    `num_predict` is set to half of `num_ctx` in both cases — comfortably above the
    resulting ceiling — so the num_predict cap never binds and the comparison isolates
    the context-derived ceiling.
    """
    small = chunk_token_budget(num_ctx=1000, num_predict=500, overhead_text="")
    large = chunk_token_budget(num_ctx=100_000, num_predict=50_000, overhead_text="")
    assert large > small * 50
