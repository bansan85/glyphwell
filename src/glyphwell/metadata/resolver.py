"""Résolution d'un identifiant IMDb vers un titre exploitable.

Le corpus ne fournit que des identifiants ; l'affichage des résultats et les filtres de
sélection du manifeste (type, année, contenu adulte) ont besoin du titre. La résolution est
exposée derrière un `Protocol` afin que les tests puissent injecter une table en mémoire
sans base SQLite.

STATUT : stubs, hors objet valeur.
"""

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol

from glyphwell.types import ImdbId

__all__ = ["SqliteTitleProvider", "Title", "TitleProvider"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Title:
    """Un titre résolu : film, série, ou épisode rattaché à sa série."""

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
        """Vrai si le titre est un épisode rattaché à une série."""
        return self.parent_imdb_id is not None

    def display_name(self) -> str:
        """Libellé lisible, pour les prompts et les exports.

        Un épisode est présenté comme ``Série S01E02 — Titre (année)``, un film comme
        ``Titre (année)``. Les parties inconnues sont simplement omises.
        """
        raise NotImplementedError


class TitleProvider(Protocol):
    """Source de titres interrogeable par identifiant IMDb."""

    def resolve(self, imdb_id: ImdbId) -> Title | None:
        """Renvoie le titre, ou `None` s'il est inconnu de cette source."""
        ...

    def resolve_many(self, imdb_ids: Iterable[ImdbId]) -> Mapping[ImdbId, Title]:
        """Résout un lot d'identifiants. Les identifiants inconnus sont absents du résultat."""
        ...


@dataclass(frozen=True, slots=True)
class SqliteTitleProvider:
    """`TitleProvider` adossé à la table `titles`, alimentée par les datasets IMDb.

    Pour un épisode, la requête joint la série parente afin que `Title.parent_title` soit
    renseigné en une seule passe.
    """

    conn: sqlite3.Connection

    def resolve(self, imdb_id: ImdbId) -> Title | None:
        """Voir `TitleProvider.resolve`."""
        raise NotImplementedError

    def resolve_many(self, imdb_ids: Iterable[ImdbId]) -> Mapping[ImdbId, Title]:
        """Voir `TitleProvider.resolve_many`."""
        raise NotImplementedError
