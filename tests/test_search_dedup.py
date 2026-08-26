"""`select_representative`: picking one subtitle file per (imdb_id, language) group."""

import pytest

from glyphwell.search.dedup import Candidate, select_representative


def _candidates(sizes: list[int]) -> list[Candidate]:
    """One candidate per size, with distinct, increasing `opensubtitles_file_id`s."""
    return [
        Candidate(file_id=i, size_bytes=size, opensubtitles_file_id=str(1000 + i))
        for i, size in enumerate(sizes)
    ]


def test_single_candidate_is_returned_unconditionally() -> None:
    (only,) = _candidates([12345])
    assert select_representative([only]) is only


def test_no_candidates_raises() -> None:
    with pytest.raises(ValueError, match="at least one candidate"):
        select_representative([])


def test_tight_group_keeps_the_largest() -> None:
    """OpenSubtitles/raw/en/1191/3276470_2741602_1_19 (9 real files, v2024/raw/en):
    no low or high outlier, so the plain maximum wins."""
    candidates = _candidates([80948, 80948, 81272, 81291, 85822, 86058, 91280, 91334, 98550])
    winner = select_representative(candidates)
    assert winner.size_bytes == 98550


def test_low_outlier_is_purged_but_the_max_survives() -> None:
    """OpenSubtitles/raw/en/1892/2 (12 real files, v2024/raw/en): a forced-only-shaped
    outlier (8136, ~20x smaller than its neighbor) is purged, but the top of the
    remaining continuum (390208) is only x1.04 above its runner-up — not a high outlier —
    so it still wins."""
    candidates = _candidates(
        [
            8136,
            159912,
            258729,
            259305,
            274970,
            282689,
            296112,
            302500,
            331367,
            337490,
            374644,
            390208,
        ]
    )
    winner = select_representative(candidates)
    assert winner.size_bytes == 390208


def test_duplicate_max_ties_break_on_lowest_opensubtitles_file_id() -> None:
    """OpenSubtitles/raw/en/2021/5012504 (5 real files, v2024/raw/en)."""
    candidates = [
        Candidate(file_id=1, size_bytes=146758, opensubtitles_file_id="10"),
        Candidate(file_id=2, size_bytes=147061, opensubtitles_file_id="20"),
        Candidate(file_id=3, size_bytes=147061, opensubtitles_file_id="21"),
        Candidate(file_id=4, size_bytes=171086, opensubtitles_file_id="99"),
        Candidate(file_id=5, size_bytes=171086, opensubtitles_file_id="30"),
    ]
    winner = select_representative(candidates)
    assert winner.size_bytes == 171086
    assert winner.opensubtitles_file_id == "30"


def test_tie_break_compares_ids_numerically_not_lexicographically() -> None:
    """ "9" < "10" lexicographically reverses the intended numeric order."""
    candidates = [
        Candidate(file_id=1, size_bytes=100, opensubtitles_file_id="10"),
        Candidate(file_id=2, size_bytes=100, opensubtitles_file_id="9"),
    ]
    winner = select_representative(candidates)
    assert winner.opensubtitles_file_id == "9"


def test_high_outlier_is_purged_in_favor_of_the_runner_up() -> None:
    """A file far above everything else (e.g. two episodes concatenated under one id)
    must not win just for being biggest."""
    candidates = _candidates([100_000, 102_000, 104_000, 20_000_000])
    winner = select_representative(candidates)
    assert winner.size_bytes == 104_000


def test_a_pair_never_loses_its_larger_candidate_to_the_high_guard() -> None:
    """With only 2 candidates, the high-outlier guard has no third point of reference to
    tell a genuinely larger transcript from an outlier, so it must not fire at all — even
    though the ratio alone (>2) would otherwise trigger it."""
    candidates = _candidates([40_000, 100_000])
    winner = select_representative(candidates)
    assert winner.size_bytes == 100_000


def test_purge_iterates_when_a_purge_exposes_a_new_extremity() -> None:
    """Purging the low outlier can reveal a new low outlier; same for the high side."""
    candidates = _candidates([100, 50_000, 51_000, 52_000, 5_000_000, 100_000_000])
    winner = select_representative(candidates)
    assert winner.size_bytes == 52_000


def test_all_zero_sizes_do_not_crash() -> None:
    """An unindexed catalog (`size_bytes` coalesced to 0) must degrade, not raise."""
    candidates = _candidates([0, 0, 0])
    winner = select_representative(candidates)
    assert winner.size_bytes == 0
