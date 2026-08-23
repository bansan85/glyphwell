"""Internal layout of the OPUS OpenSubtitles archive.

Name of the zip members, prefix included:

    <corpus>/<preprocessing>/<language>/<year>/<imdb_id>/<opensubtitles_file_id>.xml
    OpenSubtitles/raw/fr/2022/1596342/1957893755.xml

The IMDb identifier appears there **bare** (``1596342``), not in its canonical form
(``tt1596342``). All normalization is concentrated here.

Since the archive is never decompressed, these paths designate no file on disk: they are
the opening keys of `glyphwell.corpus.archive.CorpusArchive`.
"""

import re
from collections.abc import Iterator
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
    """

    rel_path: str
    language: LanguageCode
    year: int | None
    imdb_id: ImdbId
    opensubtitles_file_id: OpenSubtitlesFileId


def normalize_imdb_id(raw: str) -> ImdbId:
    """Converts an IMDb identifier to its canonical ``tt#######`` form.

    Accepts the corpus's bare form (``133093``), an already-prefixed one (``tt0133093``),
    and identifiers longer than seven digits, which are not padded.

    Args:
        raw: identifier as it appears in a path or a dataset.

    Returns:
        The canonical identifier.

    Raises:
        CorpusLayoutError: the string is not a recognizable IMDb identifier.
    """
    candidate = raw.strip()
    digits = candidate.removeprefix("tt")
    if not digits or not _IMDB_NUMERIC.fullmatch(digits):
        message = f"not a recognizable IMDb identifier: {raw!r}"
        raise CorpusLayoutError(message)
    return f"tt{digits.zfill(IMDB_ID_WIDTH)}"


def parse_entry(rel_path: Path) -> CorpusEntry:
    """Interprets a relative corpus path.

    Args:
        rel_path: name of an archive member, for example
            ``OpenSubtitles/raw/en/1999/0133093/3660124.xml``.

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
    )


def iter_corpus(
    archive: "CorpusArchive",
    *,
    language: LanguageCode | None = None,
) -> Iterator[CorpusEntry]:
    """Walks the archive and yields one entry per subtitle member.

    Generator: the archive holds hundreds of thousands of members and must never be
    materialized in memory. Names that do not follow the layout are logged then ignored,
    rather than interrupting a scan lasting several minutes.

    Args:
        archive: opened archive, never decompressed.
        language: restricts the walk to one language, or all if `None`.

    Yields:
        The entries encountered, in no guaranteed order — the planner is what sorts them.
    """
    skipped = 0
    for member in archive.iter_members():
        try:
            entry = parse_entry(Path(member.rel_path))
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
