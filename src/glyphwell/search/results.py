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
    from glyphwell.types import JsonValue, SentenceId

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


def validate_output(
    raw: str,
    *,
    output: "OutputConfig",
    match_when: str | None,
    lines_by_id: "Mapping[SentenceId, str] | None" = None,
) -> ValidatedOutput:
    """Decodes and validates the model's raw response.

    Args:
        raw: text returned by the model.
        output: manifest output configuration.
        match_when: name of the boolean field determining the match.
        lines_by_id: the chunk's own sentences, keyed by id, in chunk order. Wherever the
            response nests a sibling ``excerpt_start_id``/``excerpt_end_id`` pair, the
            ``excerpt`` field is rebuilt from these lines (every line from the first id to
            the second, inclusive, joined with ``\\n``) rather than trusted from the
            model: citing the ends of a range it already read is a far smaller generation
            than reproducing the text verbatim, and rebuilding it here guarantees an exact
            quote. The range is resolved by each id's *position* in `lines_by_id`, not by
            integer arithmetic on the id values — a sentence id is an opaque ordinal, not
            necessarily contiguous (see `CLAUDE.md`).

    Returns:
        The validated response.

    Raises:
        ModelOutputError: unreadable JSON, non-conforming to the schema, `match_when`
            field missing or not boolean, or an `excerpt_start_id`/`excerpt_end_id` that
            is not an integer, does not cite a line of the chunk, or names a range whose
            start comes after its end.
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

    payload = _reconstruct_excerpts(payload, lines_by_id=lines_by_id or {})

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


def _reconstruct_excerpts(
    payload: JsonObject, *, lines_by_id: "Mapping[SentenceId, str]"
) -> JsonObject:
    """Rebuilds every ``excerpt`` field nested anywhere in `payload` from its sibling
    ``excerpt_start_id``/``excerpt_end_id`` pair, discarding whatever the model returned
    there.
    """
    rebuilt: JsonObject = {
        key: _rebuild_excerpts(item, lines_by_id=lines_by_id) for key, item in payload.items()
    }
    if "excerpt_start_id" in rebuilt and "excerpt_end_id" in rebuilt:
        rebuilt["excerpt"] = _join_line_range(
            rebuilt["excerpt_start_id"], rebuilt["excerpt_end_id"], lines_by_id=lines_by_id
        )
    return rebuilt


def _rebuild_excerpts(
    value: "JsonValue", *, lines_by_id: "Mapping[SentenceId, str]"
) -> "JsonValue":
    """Recursive worker for `_reconstruct_excerpts`, applied to a single nested value."""
    if isinstance(value, list):
        return [_rebuild_excerpts(item, lines_by_id=lines_by_id) for item in value]
    if isinstance(value, dict):
        return _reconstruct_excerpts(value, lines_by_id=lines_by_id)
    return value


def _join_line_range(
    start_id: "JsonValue", end_id: "JsonValue", *, lines_by_id: "Mapping[SentenceId, str]"
) -> str:
    """Joins the text of every sentence from `start_id` to `end_id`, inclusive.

    The range is resolved by each id's position in `lines_by_id` (itself in chunk order),
    not by integer arithmetic on the id values: a sentence id is an opaque ordinal, not
    necessarily contiguous.
    """
    start_key = _require_cited_int("excerpt_start_id", start_id)
    end_key = _require_cited_int("excerpt_end_id", end_id)
    ordered_ids = list(lines_by_id)
    start_pos = _require_position("excerpt_start_id", start_key, ordered_ids)
    end_pos = _require_position("excerpt_end_id", end_key, ordered_ids)
    if start_pos > end_pos:
        message = (
            f"excerpt_start_id ({start_id}) comes after excerpt_end_id ({end_id}) in the excerpt"
        )
        raise ModelOutputError(message)
    return "\n".join(lines_by_id[key] for key in ordered_ids[start_pos : end_pos + 1])


def _require_cited_int(field: str, value: "JsonValue") -> str:
    """Validates a cited id is a JSON integer and returns it as a `SentenceId` key."""
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"{field} is not an integer: {value!r}"
        raise ModelOutputError(message)
    return str(value)


def _require_position(field: str, key: str, ordered_ids: "list[SentenceId]") -> int:
    """Locates `key`'s position in `ordered_ids`, or raises if it cites no chunk line."""
    try:
        return ordered_ids.index(key)
    except ValueError:
        message = f"{field} cites line {key}, which is not part of the excerpt"
        raise ModelOutputError(message) from None


def export_run(
    run_conn: "sqlite3.Connection",
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
        run_conn: run database connection. `titles`, if given, wraps a *catalog* database
            connection (`glyphwell.metadata.resolver.SqliteTitleProvider`) — the two are
            deliberately separate parameters, never a single mixed connection.
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


def summary(run_conn: "sqlite3.Connection", run_id: int) -> "Mapping[str, int]":
    """Counters for a search, for ``search status``."""
    raise NotImplementedError
