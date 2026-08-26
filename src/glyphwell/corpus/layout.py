"""Internal layout of the OPUS OpenSubtitles archive.

Name of the zip members, prefix included:

    <corpus>/<preprocessing>/<language>/<year>/<imdb_id>/<opensubtitles_file_id>.xml
    OpenSubtitles/raw/fr/2022/1596342/1957893755.xml

The IMDb identifier appears there **bare** (``1596342``), not in its canonical form
(``tt1596342``). All normalization is concentrated here.

For a TV episode, that segment is not a bare id: OPUS packs four underscore-separated
fields into it instead, ``<episode_id>_<series_id>_<season>_<episode>`` (e.g.
``674159_47763_2_13``, episode S02E13 of series ``tt0047763``, itself ``tt0674159``).
Measured on the real ``v2024``/``raw``/``en`` archive, this compound form is not an edge
case: **64.5%** of subtitle members (all TV episodes) use it. `normalize_imdb_id` keeps
only the episode's own id — see its docstring for why.

Since the archive is never decompressed, these paths designate no file on disk: they are
the opening keys of `glyphwell.corpus.archive.CorpusArchive`.
"""

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

from glyphwell.errors import CorpusLayoutError
from glyphwell.logging import get_logger
from glyphwell.types import ImdbId, LanguageCode, OpenSubtitlesFileId

if TYPE_CHECKING:
    from glyphwell.corpus.archive import CorpusArchive

_log = get_logger(__name__)

__all__ = [
    "IMDB_ID_WIDTH",
    "SUBTITLE_SUFFIXES",
    "CorpusEntry",
    "imdb_id_from_int",
    "imdb_id_to_int",
    "iter_corpus",
    "normalize_imdb_id",
    "parse_entry",
]

IMDB_ID_WIDTH: Final = 7
"""Minimum width of the numeric part of an IMDb identifier: ``tt0133093``.

Recent identifiers exceed 7 digits and are then not padded at all.
"""

SUBTITLE_SUFFIXES: Final = (".xml",)
"""Extensions of subtitle members in the archive.

Members are plain XML: the zip is the only level of compression. Any member with another
suffix is counted and flagged by ``corpus fetch`` rather than silently absorbed — that
would be the sign that this assumption has stopped being true.
"""

_IMDB_NUMERIC = re.compile(r"^\d+$")
_EPISODE_SEGMENT = re.compile(r"^(?P<episode_imdb_id>\d+)_\d+_\d+_\d+$")
"""TV-episode variant of the layout's `imdb_id` segment — see the module docstring."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusEntry:
    """A subtitle file located in the corpus layout.

    Attributes:
        rel_path: name of the member in the archive, prefix included, ``/`` separators.
            This is the file's natural key in the database, the sort key of the work
            queue, and the member's opening key.
        language: OPUS language code.
        year: year carried by the layout, `None` if the directory is not a year.
        imdb_id: canonical identifier, ``tt`` prefix included.
        opensubtitles_file_id: identifier of the subtitle on opensubtitles.org.
        size_bytes: uncompressed member size, from the archive's central directory
            (`ArchiveMember.size`) — not derived from `rel_path`, so `parse_entry` takes it
            as a parameter rather than computing it.
    """

    rel_path: str
    language: LanguageCode
    year: int | None
    imdb_id: ImdbId
    opensubtitles_file_id: OpenSubtitlesFileId
    size_bytes: int


def normalize_imdb_id(raw: str) -> ImdbId:
    """Converts an IMDb identifier to its canonical ``tt#######`` form.

    Accepts the corpus's bare form (``133093``), an already-prefixed one (``tt0133093``),
    identifiers longer than seven digits (not padded), and the TV-episode compound form
    the layout uses in place of a bare id: ``<episode_id>_<series_id>_<season>_<episode>``
    (e.g. ``674159_47763_2_13``). Only the episode's own id (the first field) is kept —
    the series id, season, and episode number are OPUS's own scrape-time copy of data the
    IMDb datasets already carry authoritatively (``title.episode.tsv``'s `parentTconst` /
    `seasonNumber` / `episodeNumber`, resolved separately by `metadata/resolver.py`), and
    spot-checking the live archive against that dataset shows the OPUS-side copy can have
    drifted from IMDb's current values, so it is never trusted here.

    Args:
        raw: identifier as it appears in a path or a dataset.

    Returns:
        The canonical identifier.

    Raises:
        CorpusLayoutError: the string is not a recognizable IMDb identifier.
    """
    candidate = raw.strip()
    episode_match = _EPISODE_SEGMENT.match(candidate)
    if episode_match is not None:
        candidate = episode_match.group("episode_imdb_id")
    digits = candidate.removeprefix("tt")
    if not digits or not _IMDB_NUMERIC.fullmatch(digits):
        message = f"not a recognizable IMDb identifier: {raw!r}"
        raise CorpusLayoutError(message)
    return f"tt{digits.zfill(IMDB_ID_WIDTH)}"


def imdb_id_to_int(imdb_id: ImdbId) -> int:
    """Numeric part of an IMDb identifier, for compact database storage.

    Accepts any form `normalize_imdb_id` accepts (bare, prefixed, the TV-episode
    compound segment): the identifier is canonicalized first, so this never silently
    stores the wrong id.

    Raises:
        CorpusLayoutError: not a recognizable IMDb identifier.
    """
    return int(normalize_imdb_id(imdb_id).removeprefix("tt"))


def imdb_id_from_int(value: int) -> ImdbId:
    """Canonical ``tt#######`` form of a numeric IMDb identifier.

    Inverse of `imdb_id_to_int`: zero-pads to `IMDB_ID_WIDTH`, exactly like
    `normalize_imdb_id`, and leaves an identifier already wider than that unpadded.
    """
    return f"tt{value:0{IMDB_ID_WIDTH}d}"


def parse_entry(rel_path: Path, *, size_bytes: int) -> CorpusEntry:
    """Interprets a relative corpus path.

    Args:
        rel_path: name of an archive member, for example
            ``OpenSubtitles/raw/en/1999/0133093/3660124.xml``.
        size_bytes: the member's uncompressed size, carried through unparsed (see
            `CorpusEntry.size_bytes`).

    Returns:
        The entry described by this path.

    Raises:
        CorpusLayoutError: the path does not follow the expected layout.
    """
    # Archive member names are always `/`-separated; `str(Path(...))` would render `\`
    # on Windows and silently corrupt the key `CorpusArchive.open_member` requires.
    posix = PurePosixPath(rel_path.as_posix())
    segments = posix.parts
    if len(segments) != 6:
        message = f"unexpected path shape ({len(segments)} segment(s)): {rel_path}"
        raise CorpusLayoutError(message)

    _corpus, _preprocessing, language, year_segment, imdb_segment, filename = segments

    suffix = next((s for s in SUBTITLE_SUFFIXES if filename.endswith(s)), None)
    if suffix is None:
        message = f"not a subtitle member: {rel_path}"
        raise CorpusLayoutError(message)
    opensubtitles_file_id = filename.removesuffix(suffix)
    if not opensubtitles_file_id:
        message = f"empty subtitle identifier: {rel_path}"
        raise CorpusLayoutError(message)

    try:
        year: int | None = int(year_segment)
    except ValueError:
        year = None

    try:
        imdb_id = normalize_imdb_id(imdb_segment)
    except CorpusLayoutError as exc:
        message = f"{rel_path}: {exc}"
        raise CorpusLayoutError(message) from exc

    return CorpusEntry(
        rel_path=posix.as_posix(),
        language=language,
        year=year,
        imdb_id=imdb_id,
        opensubtitles_file_id=opensubtitles_file_id,
        size_bytes=size_bytes,
    )


def iter_corpus(
    archive: "CorpusArchive",
    *,
    language: LanguageCode | None = None,
    on_member: Callable[[], None] | None = None,
) -> Iterator[CorpusEntry]:
    """Walks the archive and yields one entry per subtitle member.

    Generator: the archive holds hundreds of thousands of members and must never be
    materialized in memory. Names that do not follow the layout are logged then ignored,
    rather than interrupting a scan lasting several minutes.

    Args:
        archive: opened archive, never decompressed.
        language: restricts the walk to one language, or all if `None`.
        on_member: called once per member visited, whether or not it ends up parsed
            and yielded. A caller driving a progress bar off `ArchiveSummary.subtitle_count`
            (every member, any language) needs this: counting only yielded entries would
            leave the bar short by exactly the members a layout mismatch or a language
            filter discards.

    Yields:
        The entries encountered, in no guaranteed order — the planner is what sorts them.
    """
    skipped = 0
    for member in archive.iter_members():
        if on_member is not None:
            on_member()
        try:
            entry = parse_entry(Path(member.rel_path), size_bytes=member.size)
        except CorpusLayoutError as exc:
            skipped += 1
            _log.debug("skipping unparsable member: %s", exc)
            continue
        if language is not None and entry.language != language:
            continue
        yield entry
    if skipped:
        _log.warning(
            "%d member(s) did not match the expected corpus layout and were skipped", skipped
        )
