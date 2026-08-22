"""Resolving an IMDb identifier to a usable title.

The corpus only provides identifiers; displaying results and the manifest's selection
filters (type, year, adult content) need the title. Resolution is exposed behind a
`Protocol` so that tests can inject an in-memory table without a SQLite database.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from glyphwell.db.repositories import TitleRow, TitlesRepository
from glyphwell.types import ImdbId

__all__ = ["SqliteTitleProvider", "Title", "TitleProvider"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Title:
    """A resolved title: movie, series, or episode linked to its series."""

    imdb_id: ImdbId
    title_type: str | None
    primary_title: str | None
    start_year: int | None
    is_adult: bool
    parent_imdb_id: ImdbId | None = None
    parent_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None

    @property
    def is_episode(self) -> bool:
        """True if the title is an episode linked to a series."""
        return self.parent_imdb_id is not None

    def display_name(self) -> str:
        """Human-readable label, for prompts and exports.

        An episode is presented as ``Series S01E02 — Title (year)``, a movie as
        ``Title (year)``. Unknown parts are simply omitted.
        """
        year_suffix = f" ({self.start_year})" if self.start_year is not None else ""
        if not self.is_episode:
            return f"{self.primary_title or ''}{year_suffix}"

        tag = _episode_tag(self.season_number, self.episode_number)
        head = " ".join(part for part in (self.parent_title, tag) if part)
        if head and self.primary_title:
            return f"{head} — {self.primary_title}{year_suffix}"
        return f"{head or self.primary_title or ''}{year_suffix}"


def _episode_tag(season_number: int | None, episode_number: int | None) -> str:
    """``S01E02``-style tag, with an unknown season or episode simply omitted."""
    season_part = f"S{season_number:02d}" if season_number is not None else ""
    episode_part = f"E{episode_number:02d}" if episode_number is not None else ""
    return season_part + episode_part


class TitleProvider(Protocol):
    """Source of titles queryable by IMDb identifier."""

    def resolve(self, imdb_id: ImdbId) -> Title | None:
        """Returns the title, or `None` if unknown to this source."""
        ...

    def resolve_many(self, imdb_ids: Iterable[ImdbId]) -> Mapping[ImdbId, Title]:
        """Resolves a batch of identifiers. Unknown identifiers are absent from the result."""
        ...


@dataclass(frozen=True, slots=True)
class SqliteTitleProvider:
    """`TitleProvider` backed by the `titles` table, populated from the IMDb datasets.

    For an episode, a second lookup through `TitlesRepository` fetches the parent series
    so that `Title.parent_title` is filled in — going through the repository rather than
    a hand-written join keeps this module free of its own SQL.
    """

    conn: sqlite3.Connection

    def resolve(self, imdb_id: ImdbId) -> Title | None:
        """See `TitleProvider.resolve`."""
        repo = TitlesRepository(self.conn)
        row = repo.get(imdb_id)
        if row is None:
            return None
        parent = repo.get(row.parent_imdb_id) if row.parent_imdb_id is not None else None
        return _to_title(row, parent)

    def resolve_many(self, imdb_ids: Iterable[ImdbId]) -> Mapping[ImdbId, Title]:
        """See `TitleProvider.resolve_many`."""
        resolved: dict[ImdbId, Title] = {}
        for imdb_id in imdb_ids:
            title = self.resolve(imdb_id)
            if title is not None:
                resolved[imdb_id] = title
        return resolved


def _to_title(row: TitleRow, parent: TitleRow | None) -> Title:
    """Combines a title row with its resolved parent, if any, into a `Title`."""
    return Title(
        imdb_id=row.imdb_id,
        title_type=row.title_type,
        primary_title=row.primary_title,
        start_year=row.start_year,
        is_adult=row.is_adult,
        parent_imdb_id=row.parent_imdb_id,
        parent_title=parent.primary_title if parent is not None else None,
        season_number=row.season_number,
        episode_number=row.episode_number,
    )
