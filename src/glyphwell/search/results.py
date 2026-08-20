"""Validation of model responses and export of results.

The schema constraint sent to Ollama reduces deviations but does not eliminate them: the
response is therefore re-checked here against the manifest's JSON Schema before being
written.

STATUS: stubs, apart from the value object.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from glyphwell.types import JsonObject

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from glyphwell.manifest.model import OutputConfig
    from glyphwell.metadata.resolver import TitleProvider

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
    raise NotImplementedError


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
