"""A run's calibration state: sample accumulation and the response ratio it exposes."""

from glyphwell.search.calibration import Calibration
from glyphwell.tokens import (
    CALIBRATION_MARGIN_RATIO,
    CALIBRATION_MIN_CHUNK_TOKENS,
    CALIBRATION_SAMPLE_SIZE,
    DEFAULT_RESPONSE_RATIO,
)


def test_response_ratio_defaults_before_any_sample() -> None:
    assert Calibration().response_ratio == DEFAULT_RESPONSE_RATIO


def test_response_ratio_stays_default_until_enough_samples_qualify() -> None:
    calibration = Calibration()
    for _ in range(CALIBRATION_SAMPLE_SIZE - 1):
        locked = calibration.record(chunk_tokens=CALIBRATION_MIN_CHUNK_TOKENS, completion_tokens=50)
        assert locked is None
    assert calibration.response_ratio == DEFAULT_RESPONSE_RATIO


def test_record_locks_and_returns_the_ratio_exactly_once() -> None:
    calibration = Calibration()
    for _ in range(CALIBRATION_SAMPLE_SIZE - 1):
        calibration.record(chunk_tokens=1000, completion_tokens=100)
    locked = calibration.record(chunk_tokens=1000, completion_tokens=100)

    assert locked == 0.1 * (1 + CALIBRATION_MARGIN_RATIO)
    assert calibration.response_ratio == locked

    # Further samples must not move a ratio that has already locked in — that is what
    # keeps chunk sizing deterministic per manifest across a resume (CLAUDE.md §7).
    again = calibration.record(chunk_tokens=1000, completion_tokens=100_000)
    assert again is None
    assert calibration.response_ratio == locked


def test_seeding_from_an_already_locked_ratio_never_accumulates_samples() -> None:
    """A resumed run reloads a ratio already persisted (`search/engine.py::_load_calibration`)
    — no further sample should ever change it."""
    calibration = Calibration(locked_ratio=0.42)

    locked = calibration.record(chunk_tokens=1000, completion_tokens=100_000)

    assert locked is None
    assert calibration.response_ratio == 0.42
