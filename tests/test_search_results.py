"""`validate_output`: response validation and excerpt reconstruction from a cited range."""

import pytest

from glyphwell.errors import ModelOutputError
from glyphwell.manifest.model import OutputConfig
from glyphwell.search.results import validate_output


def test_reconstructs_excerpt_from_id_range() -> None:
    """Findings nesting an `excerpt_start_id`/`excerpt_end_id` pair get their `excerpt`
    rebuilt from the chunk's own text, overwriting anything the model returned there."""
    raw = (
        '{"matched": true, "findings": '
        '[{"excerpt_start_id": 1, "excerpt_end_id": 2, "excerpt": "model guess"}]}'
    )
    validated = validate_output(
        raw,
        output=OutputConfig(format="json"),
        match_when="matched",
        lines_by_id={"1": "Hello", "2": "world"},
    )
    assert validated.matched is True
    assert validated.payload is not None
    findings = validated.payload["findings"]
    assert isinstance(findings, list)
    (finding,) = findings
    assert isinstance(finding, dict)
    assert finding["excerpt"] == "Hello\nworld"


def test_excerpt_range_includes_lines_not_individually_cited() -> None:
    """The reconstructed excerpt spans every line between the two ids, not just the two
    cited ends — this is the point of a range over a flat id list."""
    raw = '{"matched": true, "findings": [{"excerpt_start_id": 1, "excerpt_end_id": 3}]}'
    validated = validate_output(
        raw,
        output=OutputConfig(format="json"),
        match_when="matched",
        lines_by_id={"1": "one", "2": "two", "3": "three"},
    )
    assert validated.payload is not None
    findings = validated.payload["findings"]
    assert isinstance(findings, list)
    (finding,) = findings
    assert isinstance(finding, dict)
    assert finding["excerpt"] == "one\ntwo\nthree"


def test_unrelated_payload_is_left_untouched() -> None:
    """A response with no `excerpt_start_id`/`excerpt_end_id` anywhere goes through
    unchanged."""
    raw = '{"matched": false}'
    validated = validate_output(
        raw, output=OutputConfig(format="json"), match_when="matched", lines_by_id={}
    )
    assert validated.matched is False
    assert validated.payload == {"matched": False}


def test_cited_id_outside_the_chunk_is_rejected() -> None:
    raw = '{"matched": true, "findings": [{"excerpt_start_id": 99, "excerpt_end_id": 99}]}'
    with pytest.raises(ModelOutputError, match="excerpt_start_id cites line 99"):
        validate_output(
            raw,
            output=OutputConfig(format="json"),
            match_when="matched",
            lines_by_id={"1": "Hello"},
        )


def test_non_integer_cited_id_is_rejected() -> None:
    raw = '{"matched": true, "findings": [{"excerpt_start_id": "1", "excerpt_end_id": 1}]}'
    with pytest.raises(ModelOutputError, match="not an integer"):
        validate_output(
            raw,
            output=OutputConfig(format="json"),
            match_when="matched",
            lines_by_id={"1": "Hello"},
        )


def test_inverted_range_is_rejected() -> None:
    """A start id positioned after the end id in chunk order is not a valid range,
    regardless of the two ids' numeric values."""
    raw = '{"matched": true, "findings": [{"excerpt_start_id": 2, "excerpt_end_id": 1}]}'
    with pytest.raises(ModelOutputError, match=r"excerpt_start_id .* comes after excerpt_end_id"):
        validate_output(
            raw,
            output=OutputConfig(format="json"),
            match_when="matched",
            lines_by_id={"1": "Hello", "2": "world"},
        )


def test_missing_lines_by_id_still_validates_a_payload_without_citations() -> None:
    """The default (no `lines_by_id`) must not break ordinary manifests."""
    raw = '{"matched": true}'
    validated = validate_output(raw, output=OutputConfig(format="json"), match_when="matched")
    assert validated.matched is True
