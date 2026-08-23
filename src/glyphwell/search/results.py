"""Validation of model responses and export of results.

The schema constraint sent to Ollama reduces deviations but does not eliminate them: the
response is therefore re-checked here against the manifest's JSON Schema before being
written.

STATUS: `validate_output` is implemented; `export_run` and `summary` (``search export``
and ``search status``) remain stubs.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

import jsonschema
from pydantic import TypeAdapter, ValidationError

from glyphwell.errors import ModelOutputError
from glyphwell.types import JsonObject

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from glyphwell.manifest.model import OutputConfig
    from glyphwell.metadata.resolver import TitleProvider

_JSON_OBJECT_ADAPTER: Final[TypeAdapter[JsonObject]] = TypeAdapter(JsonObject)

__all__ = ["ExportFormat", "ValidatedOutput", "export_run", "validate_output"]


class ExportFormat(StrEnum):
    """Available export formats."""

    JSONL = "jsonl"
    CSV = "csv"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedOutput:
    """Model response after verification.

    Attributes:
        payload: JSON object conforming to the schema, or `None` for text output.
        matched: value of the field designated by ``match_when``. True by default when
            the manifest designates none.
    """

    payload: JsonObject | None
    matched: bool


def validate_output(raw: str, *, output: "OutputConfig", match_when: str | None) -> ValidatedOutput:
    """Decodes and validates the model's raw response.

    Args:
        raw: text returned by the model.
        output: manifest output configuration.
        match_when: name of the boolean field determining the match.

    Returns:
        The validated response.

    Raises:
        ModelOutputError: unreadable JSON, non-conforming to the schema, or `match_when`
            field missing or not boolean.
    """
    if output.format == "text":
        # `SearchManifest` forbids `match_when` together with `format = text`: nothing
        # to check it against, every produced chunk counts as a match.
        return ValidatedOutput(payload=None, matched=True)

    try:
        payload = _JSON_OBJECT_ADAPTER.validate_json(raw)
    except ValidationError as exc:
        message = f"model response is not a valid JSON object: {exc}"
        raise ModelOutputError(message) from exc

    if output.json_schema is not None:
        try:
            jsonschema.validate(payload, output.json_schema)
        except jsonschema.ValidationError as exc:
            message = f"response does not conform to output.schema: {exc.message}"
            raise ModelOutputError(message) from exc

    if match_when is None:
        return ValidatedOutput(payload=payload, matched=True)
    if match_when not in payload:
        message = f"match_when field {match_when!r} missing from response"
        raise ModelOutputError(message)
    matched = payload[match_when]
    if not isinstance(matched, bool):
        message = f"match_when field {match_when!r} is not a boolean: {matched!r}"
        raise ModelOutputError(message)
    return ValidatedOutput(payload=payload, matched=matched)


def export_run(
    conn: "sqlite3.Connection",
    *,
    run_id: int,
    dest: "Path",
    export_format: ExportFormat,
    titles: "TitleProvider | None" = None,
    matched_only: bool = True,
) -> int:
    """Writes a search's results to a file and returns the number of lines.

    Titles are resolved at export time, not stored in `results`: a re-import of the IMDb
    datasets thus improves subsequent exports without touching the results.

    Args:
        conn: database connection.
        run_id: search to export.
        dest: output file.
        export_format: write format.
        titles: source of titles, to enrich each line.
        matched_only: export matches only.

    Raises:
        SearchError: unknown search.
        OSError: write failed.
    """
    raise NotImplementedError


def summary(conn: "sqlite3.Connection", run_id: int) -> "Mapping[str, int]":
    """Counters for a search, for ``search status``."""
    raise NotImplementedError
