"""Picks one representative subtitle file per `(imdb_id, language)` group.

OpenSubtitles frequently carries several independent translations for the same title —
one directory in the OPUS archive can hold anywhere from a couple to a dozen+ member
files. Sending every one of them through Ollama multiplies the model-call cost of a search
without a proportional gain: most of that redundancy is either near-duplicate uploads or
degenerate variants (forced-only or commentary-track subtitles, an order of magnitude
shorter than a full dialogue transcript).

`select_representative` picks the file most likely to carry the fullest, legitimate
dialogue transcript, using `size_bytes` alone (a free signal — see
`corpus/layout.py::CorpusEntry.size_bytes`, no member content read). See ADR-0020 for the
alternatives ruled out (max alone, a trimmed mean) and the empirical percentiles behind the
two thresholds below, measured on the real `v2024`/`raw`/`en` archive.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from statistics import median
from typing import Final

from glyphwell.types import OpenSubtitlesFileId

__all__ = ["Candidate", "select_representative"]

_LOW_OUTLIER_RATIO: Final[float] = 0.5
"""A candidate below this fraction of the group's (current) median is purged as a
degenerate outlier (forced-only / commentary-track subtitle).

Measured on 241,285 real duplicate groups: the typical group's smallest file already sits
at 90%+ of the group median (p50 = 0.956, p25 = 0.90, p10 = 0.79), while a genuine
forced/commentary outlier sits close to an order of magnitude below it (p5 = 0.58,
p1 = 0.0275). 0.5 sits inside that gap — see ADR-0020.
"""

_HIGH_OUTLIER_RATIO: Final[float] = 2.0
"""The current maximum is purged as suspect (a different cut, a concatenated release...)
when it exceeds this multiple of the runner-up.

Measured on the same 241,285 groups: normal variation between the top two candidates
essentially never exceeds x1.4 (p95 = 1.366); x2.0 sits past p99 (2.286), catching only the
long tail (p99.9 = x28.5, max observed = x189) without ever touching the ordinary
dialogue-vs-SDH gap. See ADR-0020.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class Candidate:
    """One subtitle file competing to represent its `(imdb_id, language)` group."""

    file_id: int
    size_bytes: int
    opensubtitles_file_id: OpenSubtitlesFileId
    """Tie-break key when several candidates share the winning `size_bytes` — compared
    numerically, never lexicographically (see `select_representative`)."""


def select_representative(candidates: Iterable[Candidate]) -> Candidate:
    """Picks the file most likely to carry the fullest, legitimate dialogue transcript.

    Purges degenerate low outliers first, then a maximum that stands disproportionately
    above its runner-up, and returns whatever remains largest. Both purges are iterative:
    a purge can expose a new extremity that itself warrants purging (see ADR-0020).

    The high-outlier purge requires at least 3 remaining candidates: with only 2, the
    "runner-up" the maximum is compared against is the same lone alternative the low-outlier
    purge already had a chance to judge, and a bigger-is-suspect ratio test cannot tell a
    genuinely larger transcript from an outlier without a third point of reference — it
    would otherwise risk discarding the larger, legitimate file of a pair.

    Ties (identical `size_bytes`) are broken on the lowest `opensubtitles_file_id`, parsed
    as an integer — the identifier is numeric but stored as `str` (`OpenSubtitlesFileId`),
    and comparing it lexicographically would misorder ids of different digit counts.

    Raises:
        ValueError: `candidates` is empty.
    """
    pool = sorted(candidates, key=lambda c: c.size_bytes)
    if not pool:
        message = "select_representative() requires at least one candidate"
        raise ValueError(message)

    while len(pool) >= 2:
        group_median = median(c.size_bytes for c in pool)
        if group_median <= 0 or pool[0].size_bytes >= _LOW_OUTLIER_RATIO * group_median:
            break
        pool.pop(0)

    while len(pool) >= 3 and pool[-2].size_bytes > 0:
        if pool[-1].size_bytes / pool[-2].size_bytes <= _HIGH_OUTLIER_RATIO:
            break
        pool.pop()

    winning_size = pool[-1].size_bytes
    return min(
        (c for c in pool if c.size_bytes == winning_size),
        key=lambda c: int(c.opensubtitles_file_id),
    )
