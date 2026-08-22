"""Resolving an IMDb identifier to a title, and formatting it for display."""

import sqlite3

from glyphwell.db.repositories import TitleRow, TitlesRepository
from glyphwell.metadata.resolver import SqliteTitleProvider, Title


def _title(
    *,
    imdb_id: str = "tt0133093",
    title_type: str | None = "movie",
    primary_title: str | None = "The Matrix",
    start_year: int | None = 1999,
    is_adult: bool = False,
    parent_imdb_id: str | None = None,
    parent_title: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> Title:
    return Title(
        imdb_id=imdb_id,
        title_type=title_type,
        primary_title=primary_title,
        start_year=start_year,
        is_adult=is_adult,
        parent_imdb_id=parent_imdb_id,
        parent_title=parent_title,
        season_number=season_number,
        episode_number=episode_number,
    )


def test_movie_display_name() -> None:
    assert _title().display_name() == "The Matrix (1999)"


def test_movie_without_year() -> None:
    assert _title(start_year=None).display_name() == "The Matrix"


def test_episode_display_name() -> None:
    episode = _title(
        imdb_id="tt0041039",
        title_type="tvEpisode",
        primary_title="The Episode",
        start_year=1950,
        parent_imdb_id="tt0041038",
        parent_title="The Series",
        season_number=1,
        episode_number=9,
    )
    assert episode.display_name() == "The Series S01E09 — The Episode (1950)"


def test_episode_with_unknown_parent_title_omits_it() -> None:
    """The parent link is known, but the parent's own row could not be resolved."""
    episode = _title(
        title_type="tvEpisode",
        primary_title="The Episode",
        parent_imdb_id="tt0041038",
        parent_title=None,
        season_number=1,
        episode_number=9,
    )
    assert episode.display_name() == "S01E09 — The Episode (1999)"


def test_episode_with_unknown_episode_title() -> None:
    episode = _title(
        title_type="tvEpisode",
        primary_title=None,
        parent_imdb_id="tt0041038",
        parent_title="The Series",
        season_number=1,
        episode_number=9,
    )
    assert episode.display_name() == "The Series S01E09 (1999)"


def _movie_row(
    *,
    imdb_id: str = "tt0133093",
    title_type: str | None = "movie",
    primary_title: str | None = "The Matrix",
    parent_imdb_id: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
) -> TitleRow:
    return TitleRow(
        imdb_id=imdb_id,
        title_type=title_type,
        primary_title=primary_title,
        original_title=primary_title,
        start_year=1999,
        end_year=None,
        is_adult=False,
        runtime_minutes=136,
        parent_imdb_id=parent_imdb_id,
        season_number=season_number,
        episode_number=episode_number,
    )


def test_resolve_of_unknown_id_is_none(db: sqlite3.Connection) -> None:
    assert SqliteTitleProvider(db).resolve("tt9999999") is None


def test_resolve_a_movie(db: sqlite3.Connection) -> None:
    TitlesRepository(db).upsert_many([_movie_row()])

    found = SqliteTitleProvider(db).resolve("tt0133093")

    assert found is not None
    assert found.primary_title == "The Matrix"
    assert not found.is_episode
    assert found.parent_title is None


def test_resolve_an_episode_joins_the_parent_title(db: sqlite3.Connection) -> None:
    repo = TitlesRepository(db)
    repo.upsert_many(
        [
            _movie_row(imdb_id="tt0041038", title_type="tvSeries", primary_title="The Series"),
            _movie_row(
                imdb_id="tt0041039",
                title_type="tvEpisode",
                primary_title="The Episode",
                parent_imdb_id="tt0041038",
                season_number=1,
                episode_number=9,
            ),
        ]
    )

    found = SqliteTitleProvider(db).resolve("tt0041039")

    assert found is not None
    assert found.is_episode
    assert found.parent_title == "The Series"
    assert found.display_name() == "The Series S01E09 — The Episode (1999)"


def test_resolve_many_skips_unknown_ids(db: sqlite3.Connection) -> None:
    TitlesRepository(db).upsert_many([_movie_row()])

    found = SqliteTitleProvider(db).resolve_many(["tt0133093", "tt9999999"])

    assert set(found) == {"tt0133093"}
    assert found["tt0133093"].primary_title == "The Matrix"
