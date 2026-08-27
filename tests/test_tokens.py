"""Token-count estimation and chunk token budgeting."""

import math

import pytest

from glyphwell.errors import ManifestError
from glyphwell.tokens import (
    CALIBRATION_MARGIN_RATIO,
    CALIBRATION_MIN_CHUNK_TOKENS,
    CALIBRATION_SAMPLE_SIZE,
    CHARS_PER_TOKEN,
    DEFAULT_RESPONSE_RATIO,
    SAFETY_MARGIN_RATIO,
    calibrate_response_ratio,
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


def test_chunk_token_budget_default_response_ratio_matches_num_predict() -> None:
    """No `response_ratio` given reproduces ADR-0021's original, uncalibrated cap."""
    budget = chunk_token_budget(num_ctx=24576, num_predict=1024, overhead_text="short overhead")
    assert budget == math.floor(1024 / DEFAULT_RESPONSE_RATIO)


def test_chunk_token_budget_a_smaller_response_ratio_widens_the_predict_cap() -> None:
    """ADR-0022: a calibrated ratio below 1.0 (a task whose response does not scale much
    with its input) raises the num_predict-derived cap, and therefore densifies chunks —
    still bounded by the context ceiling, exercised separately above."""
    default_ratio_budget = chunk_token_budget(num_ctx=100_000, num_predict=1024, overhead_text="")
    calibrated_budget = chunk_token_budget(
        num_ctx=100_000, num_predict=1024, overhead_text="", response_ratio=0.2
    )
    assert calibrated_budget == math.floor(1024 / 0.2)
    assert calibrated_budget > default_ratio_budget


def test_calibrate_response_ratio_is_none_below_the_sample_size() -> None:
    samples = [(CALIBRATION_MIN_CHUNK_TOKENS, 50)] * (CALIBRATION_SAMPLE_SIZE - 1)
    assert calibrate_response_ratio(samples) is None


def test_calibrate_response_ratio_locks_the_margin_adjusted_worst_ratio() -> None:
    """The worst (highest) ratio drives the result, not an average — a single denser
    chunk in the sample must not be diluted away by many low-ratio ones."""
    samples = [(1000, 100)] * (CALIBRATION_SAMPLE_SIZE - 1) + [(1000, 400)]
    ratio = calibrate_response_ratio(samples)
    assert ratio == pytest.approx(0.4 * (1 + CALIBRATION_MARGIN_RATIO))


def test_calibrate_response_ratio_excludes_near_empty_chunks() -> None:
    """A tiny chunk that happens to score a large completion must not dominate the
    max-based statistic — see `CALIBRATION_MIN_CHUNK_TOKENS`'s docstring."""
    noisy_outlier = (10, 500)  # ratio 50.0, but far below CALIBRATION_MIN_CHUNK_TOKENS
    samples = [noisy_outlier] + [(1000, 100)] * CALIBRATION_SAMPLE_SIZE
    ratio = calibrate_response_ratio(samples)
    assert ratio == pytest.approx(0.1 * (1 + CALIBRATION_MARGIN_RATIO))


def test_calibrate_response_ratio_is_none_when_every_qualifying_completion_is_empty() -> None:
    samples = [(CALIBRATION_MIN_CHUNK_TOKENS, 0)] * CALIBRATION_SAMPLE_SIZE
    assert calibrate_response_ratio(samples) is None
