"""`validate_output`: response validation and excerpt reconstruction from cited ids."""

import pytest

from glyphwell.errors import ModelOutputError
from glyphwell.manifest.model import OutputConfig
from glyphwell.search.results import validate_output


def test_reconstructs_excerpt_from_cited_ids() -> None:
    """Findings nesting an `excerpt_ids` array get their `excerpt` rebuilt from the
    chunk's own text, overwriting anything the model returned there."""
    raw = '{"matched": true, "findings": [{"excerpt_ids": [1, 2], "excerpt": "model guess"}]}'
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


def test_unrelated_payload_is_left_untouched() -> None:
    """A response with no `excerpt_ids` anywhere goes through unchanged."""
    raw = '{"matched": false}'
    validated = validate_output(
        raw, output=OutputConfig(format="json"), match_when="matched", lines_by_id={}
    )
    assert validated.matched is False
    assert validated.payload == {"matched": False}


def test_cited_id_outside_the_chunk_is_rejected() -> None:
    raw = '{"matched": true, "findings": [{"excerpt_ids": [99]}]}'
    with pytest.raises(ModelOutputError, match="excerpt_ids cites line 99"):
        validate_output(
            raw,
            output=OutputConfig(format="json"),
            match_when="matched",
            lines_by_id={"1": "Hello"},
        )


def test_non_integer_cited_id_is_rejected() -> None:
    raw = '{"matched": true, "findings": [{"excerpt_ids": ["1"]}]}'
    with pytest.raises(ModelOutputError, match="not an integer"):
        validate_output(
            raw,
            output=OutputConfig(format="json"),
            match_when="matched",
            lines_by_id={"1": "Hello"},
        )


def test_missing_lines_by_id_still_validates_a_payload_without_citations() -> None:
    """The default (no `lines_by_id`) must not break ordinary manifests."""
    raw = '{"matched": true}'
    validated = validate_output(raw, output=OutputConfig(format="json"), match_when="matched")
    assert validated.matched is True
