"""Textual prefilter applied before a model call."""

import pytest

from glyphwell.errors import ManifestError
from glyphwell.manifest.model import PrefilterConfig, PrefilterMode
from glyphwell.manifest.prefilter import Prefilter


def test_off_mode_keeps_everything_regardless_of_patterns() -> None:
    prefilter = Prefilter.compile(PrefilterConfig(mode=PrefilterMode.OFF))
    assert prefilter.enabled is False
    assert prefilter.keeps("completely unrelated text") is True


def test_any_mode_requires_at_least_one_match() -> None:
    prefilter = Prefilter.compile(
        PrefilterConfig(mode=PrefilterMode.ANY, patterns=("ski", "snowboard"))
    )
    assert prefilter.enabled is True
    assert prefilter.keeps("we went skiing yesterday") is True
    assert prefilter.keeps("we went hiking yesterday") is False


def test_all_mode_requires_every_pattern() -> None:
    prefilter = Prefilter.compile(
        PrefilterConfig(mode=PrefilterMode.ALL, patterns=("ski", "piste"))
    )
    assert prefilter.keeps("the ski piste was icy") is True
    assert prefilter.keeps("the ski trip was fun") is False


def test_none_mode_requires_no_pattern_present() -> None:
    prefilter = Prefilter.compile(PrefilterConfig(mode=PrefilterMode.NONE, patterns=("ski",)))
    assert prefilter.keeps("a quiet dinner scene") is True
    assert prefilter.keeps("we went skiing") is False


def test_case_insensitive_by_default() -> None:
    prefilter = Prefilter.compile(PrefilterConfig(mode=PrefilterMode.ANY, patterns=("ski",)))
    assert prefilter.keeps("SKI resort") is True


def test_case_sensitive_when_requested() -> None:
    prefilter = Prefilter.compile(
        PrefilterConfig(mode=PrefilterMode.ANY, patterns=("ski",), case_sensitive=True)
    )
    assert prefilter.keeps("SKI resort") is False
    assert prefilter.keeps("a ski resort") is True


def test_literal_pattern_with_regex_metacharacters_matches_literally() -> None:
    prefilter = Prefilter.compile(PrefilterConfig(mode=PrefilterMode.ANY, patterns=("3.5",)))
    assert prefilter.keeps("version 3.5 released") is True
    assert prefilter.keeps("version 3X5 released") is False


def test_regex_mode_interprets_patterns_as_regular_expressions() -> None:
    prefilter = Prefilter.compile(
        PrefilterConfig(mode=PrefilterMode.ANY, patterns=(r"\bski(ing)?\b",), regex=True)
    )
    assert prefilter.keeps("we are skiing today") is True
    assert prefilter.keeps("skiff") is False


def test_invalid_regex_is_rejected() -> None:
    with pytest.raises(ManifestError):
        Prefilter.compile(
            PrefilterConfig(mode=PrefilterMode.ANY, patterns=("(unclosed",), regex=True)
        )
