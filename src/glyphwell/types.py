"""Shared type aliases (PEP 695).

These aliases are lazy and have no runtime cost. They make signatures readable and
distinguish identifiers that are all strings but not interchangeable: an IMDb
identifier, an opensubtitles.org subtitle identifier, and a sentence identifier have
neither the same domain nor the same origin.
"""

from pydantic import JsonValue

__all__ = [
    "ImdbId",
    "JsonObject",
    "JsonValue",
    "LanguageCode",
    "OpenSubtitlesFileId",
    "OpusVersion",
    "SentenceId",
    "Sha256",
]

type ImdbId = str
"""Canonical IMDb identifier, prefix included: ``tt0133093``.

The OPUS archive carries the bare form (``133093``, ``1596342``) in its paths;
normalization to this canonical form is centralized in `glyphwell.corpus.layout`.
"""

type OpenSubtitlesFileId = str
"""Subtitle identifier on opensubtitles.org: ``1957893755``.

It's what the file name carries in the OPUS archive. It designates a specific
*translation*, whereas `ImdbId` designates the work: a single film has one `ImdbId`
and as many subtitle identifiers as published versions. Lets you trace back to
``https://www.opensubtitles.org/en/subtitles/<id>``.
"""

type SentenceId = str
"""``id`` attribute of an ``<s>`` tag in the OPUS XML.

An **opaque** ordinal: ordered, but not necessarily contiguous or purely numeric. The
position in the stream (`Sentence.index`) is the authority for resumption; this
identifier is kept only for traceability.
"""

type LanguageCode = str
"""Language code as used by OPUS: ``en``, ``fr``, ..."""

type OpusVersion = str
"""Version of an OPUS release: ``v2024``."""

type Sha256 = str
"""SHA-256 checksum in lowercase hexadecimal."""

type JsonObject = dict[str, JsonValue]
"""Any JSON object.

Used at untyped boundaries (YAML, model response) in place of ``Any``, which mypy
forbids in this project.
"""
