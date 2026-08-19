"""Accès typé aux tables.

Le reste du code ne construit jamais de SQL : il passe par ces dépôts, qui traduisent les
lignes SQLite en objets valeur. C'est aussi le seul endroit où les invariants de la reprise
se traduisent en requêtes (``INSERT OR IGNORE``, tri déterministe, transaction par fenêtre).

STATUT : stubs. Les signatures et les objets valeur sont définitifs ; les corps restent à
écrire (cf. section « Périmètre actuel » de CLAUDE.md).
"""

import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from glyphwell.types import ImdbId, JsonObject, LanguageCode, OpusFileId, OpusVersion, Sha256

__all__ = [
    "FileStatus",
    "ResultRow",
    "ResultsRepository",
    "RunFileRow",
    "RunFilesRepository",
    "RunRow",
    "RunStatus",
    "RunsRepository",
    "SubtitleFileRow",
    "SubtitleFilesRepository",
    "TitleRow",
    "TitlesRepository",
]


class RunStatus(StrEnum):
    """Cycle de vie d'une recherche."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    DONE = "done"
    FAILED = "failed"


class FileStatus(StrEnum):
    """Cycle de vie d'un fichier au sein d'une recherche.

    ``IN_PROGRESS`` est un état légitime après une interruption : le curseur
    (`RunFileRow.last_sentence_index`) reste cohérent et la reprise repart de là.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass(frozen=True, slots=True, kw_only=True)
class TitleRow:
    """Une ligne de `titles`."""

    imdb_id: ImdbId
    title_type: str | None
    primary_title: str | None
    original_title: str | None
    start_year: int | None
    end_year: int | None
    is_adult: bool
    runtime_minutes: int | None
    parent_imdb_id: ImdbId | None
    season_number: int | None
    episode_number: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class SubtitleFileRow:
    """Une ligne de `subtitle_files`."""

    file_id: int
    opus_version: OpusVersion
    language: LanguageCode
    imdb_id: ImdbId
    opus_file_id: OpusFileId
    rel_path: str
    year: int | None
    sha256: Sha256 | None
    size_bytes: int | None
    sentence_count: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class RunRow:
    """Une ligne de `runs`."""

    run_id: int
    manifest_path: str
    manifest_hash: Sha256
    model: str
    status: RunStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class RunFileRow:
    """Une ligne de `run_files` : état d'un fichier dans une recherche.

    `last_sentence_index` est le curseur de reprise ; `None` signifie « pas encore
    commencé ».
    """

    run_id: int
    file_id: int
    status: FileStatus
    file_sha256: Sha256 | None
    last_sentence_index: int | None
    last_sentence_id: str | None
    chunks_done: int
    error: str | None


@dataclass(frozen=True, slots=True, kw_only=True)
class ResultRow:
    """Une ligne de `results` : la réponse du modèle pour une fenêtre."""

    result_id: int
    run_id: int
    file_id: int
    chunk_index: int
    first_sentence_index: int
    last_sentence_index: int
    matched: bool
    payload: JsonObject | None
    model: str
    latency_ms: int | None


@dataclass(frozen=True, slots=True)
class TitlesRepository:
    """Lecture et écriture de `titles`."""

    conn: sqlite3.Connection

    def get(self, imdb_id: ImdbId) -> TitleRow | None:
        """Renvoie le titre, ou `None` s'il n'a pas été importé."""
        raise NotImplementedError

    def upsert_many(self, rows: Sequence[TitleRow]) -> int:
        """Insère ou met à jour un lot de titres, et renvoie le nombre de lignes écrites."""
        raise NotImplementedError

    def count(self) -> int:
        """Nombre de titres connus."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class SubtitleFilesRepository:
    """Catalogue des fichiers du corpus."""

    conn: sqlite3.Connection

    def upsert(self, row: SubtitleFileRow) -> int:
        """Insère ou met à jour un fichier, et renvoie son `file_id`."""
        raise NotImplementedError

    def get_by_path(
        self,
        *,
        opus_version: OpusVersion,
        language: LanguageCode,
        rel_path: str,
    ) -> SubtitleFileRow | None:
        """Retrouve un fichier par sa clé naturelle."""
        raise NotImplementedError

    def set_hash(self, file_id: int, sha256: Sha256, *, size_bytes: int) -> None:
        """Enregistre l'empreinte d'un fichier."""
        raise NotImplementedError

    def iter_stale(self) -> Iterator[SubtitleFileRow]:
        """Fichiers dont l'empreinte est absente ou périmée, à re-hacher."""
        raise NotImplementedError

    def count(self) -> int:
        """Nombre de fichiers catalogués."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RunsRepository:
    """Cycle de vie des recherches."""

    conn: sqlite3.Connection

    def create(
        self,
        *,
        manifest_path: str,
        manifest_hash: Sha256,
        manifest_snapshot: str,
        model: str,
    ) -> int:
        """Crée une recherche et renvoie son `run_id`."""
        raise NotImplementedError

    def get(self, run_id: int) -> RunRow | None:
        """Renvoie une recherche, ou `None`."""
        raise NotImplementedError

    def find_by_hash(self, manifest_hash: Sha256) -> Sequence[RunRow]:
        """Recherches déjà lancées pour ce manifeste, du plus récent au plus ancien."""
        raise NotImplementedError

    def set_status(self, run_id: int, status: RunStatus) -> None:
        """Change le statut d'une recherche."""
        raise NotImplementedError

    def list_all(self) -> Sequence[RunRow]:
        """Toutes les recherches, du plus récent au plus ancien."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RunFilesRepository:
    """File de travail et curseurs de reprise."""

    conn: sqlite3.Connection

    def enqueue_many(self, run_id: int, file_ids: Sequence[int]) -> int:
        """Ajoute des fichiers à la file, sans écraser ceux déjà présents.

        Idempotent : réutilisable pour compléter la file d'un run existant quand de
        nouveaux fichiers apparaissent dans le corpus.
        """
        raise NotImplementedError

    def iter_pending(self, run_id: int) -> Iterator[RunFileRow]:
        """Fichiers non terminés, dans l'ordre déterministe ``ORDER BY rel_path``.

        L'ordre est ce qui rend `chunk_index` stable entre deux exécutions : sans lui, une
        reprise ne désignerait pas les mêmes fenêtres.
        """
        raise NotImplementedError

    def get(self, run_id: int, file_id: int) -> RunFileRow | None:
        """État d'un fichier dans une recherche."""
        raise NotImplementedError

    def mark_started(self, run_id: int, file_id: int) -> None:
        """Passe un fichier en `IN_PROGRESS`."""
        raise NotImplementedError

    def mark_done(self, run_id: int, file_id: int) -> None:
        """Passe un fichier en `DONE`."""
        raise NotImplementedError

    def mark_error(self, run_id: int, file_id: int, error: str) -> None:
        """Passe un fichier en `ERROR` en conservant son curseur, pour permettre la reprise."""
        raise NotImplementedError

    def reset(self, file_id: int) -> int:
        """Remet un fichier à `PENDING` dans toutes les recherches et efface son curseur.

        Appelé quand l'empreinte du fichier a changé. Ne touche qu'à ce fichier : le reste
        de chaque recherche est conservé.
        """
        raise NotImplementedError

    def progress(self, run_id: int) -> dict[FileStatus, int]:
        """Compte les fichiers par statut, pour ``search status``."""
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class ResultsRepository:
    """Résultats produits par le modèle."""

    conn: sqlite3.Connection

    def insert_ignore(self, row: ResultRow) -> bool:
        """Insère un résultat, sans effet s'il existe déjà.

        Renvoie vrai si une ligne a été écrite. Le doublon n'est pas une erreur : c'est le
        cas normal quand une fenêtre est rejouée après une interruption.
        """
        raise NotImplementedError

    def delete_for_file(self, file_id: int) -> int:
        """Supprime tous les résultats d'un fichier, toutes recherches confondues.

        Utilisé à l'invalidation quand le sous-titre a changé de contenu.
        """
        raise NotImplementedError

    def iter_matches(self, run_id: int) -> Iterator[ResultRow]:
        """Résultats positifs d'une recherche, pour l'export."""
        raise NotImplementedError

    def count(self, run_id: int, *, matched_only: bool = False) -> int:
        """Nombre de résultats d'une recherche."""
        raise NotImplementedError
