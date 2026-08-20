"""Resolving an IMDb identifier to a usable title.

The corpus only provides identifiers; displaying results and the manifest's selection
filters (type, year, adult content) need the title. Resolution is exposed behind a
`Protocol` so that tests can inject an in-memory table without a SQLite database.

STATUS: stubs, apart from the value object.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

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
        raise NotImplementedError


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

    For an episode, the query joins the parent series so that `Title.parent_title` is
    filled in a single pass.
    """

    conn: sqlite3.Connection

    def resolve(self, imdb_id: ImdbId) -> Title | None:
        """See `TitleProvider.resolve`."""
        raise NotImplementedError

    def resolve_many(self, imdb_ids: Iterable[ImdbId]) -> Mapping[ImdbId, Title]:
        """See `TitleProvider.resolve_many`."""
        raise NotImplementedError
