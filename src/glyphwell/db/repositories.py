"""Accès typé aux tables.

Le reste du code ne construit jamais de SQL : il passe par ces dépôts, qui traduisent les
lignes SQLite en objets valeur. C'est aussi le seul endroit où les invariants de la reprise
se traduisent en requêtes (``INSERT OR IGNORE``, tri déterministe, transaction par fenêtre).

STATUT : `CorpusDownloadsRepository` est implémenté ; le reste est encore en stubs, dont
les signatures et les objets valeur sont définitifs (cf. « Périmètre actuel » de
CLAUDE.md).
"""

import sqlite3
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum

from glyphwell.types import (
    ImdbId,
    JsonObject,
    LanguageCode,
    OpenSubtitlesFileId,
    OpusVersion,
    Sha256,
)

__all__ = [
    "CorpusDownloadRow",
    "CorpusDownloadsRepository",
    "DownloadStatus",
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


class DownloadStatus(StrEnum):
    """Cycle de vie d'une acquisition du corpus.

    Il n'y a pas d'état ``extracted`` : l'archive n'est jamais décompressée.
    """

    PENDING = "pending"
    DOWNLOADED = "downloaded"
    FAILED = "failed"


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
    opensubtitles_file_id: OpenSubtitlesFileId
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


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusDownloadRow:
    """Une ligne de `corpus_downloads` : la traçabilité d'une acquisition.

    `download_id` vaut `None` tant que la ligne n'a pas été écrite, ce qui rend l'objet
    utilisable aussi bien en insertion qu'en lecture.
    """

    download_id: int | None = None
    opus_corpus: str
    opus_version: OpusVersion
    language: LanguageCode
    url: str | None
    archive_path: str | None
    sha256: Sha256 | None
    status: DownloadStatus
    downloaded_at: str | None = None
    verified_at: str | None = None


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


@dataclass(frozen=True, slots=True)
class CorpusDownloadsRepository:
    """Traçabilité des téléchargements du corpus.

    Une ligne par ``(corpus, version, langue)``. Elle est écrite en ``pending`` *avant* le
    transfert : une base absente doit faire échouer ``corpus fetch`` tout de suite, pas
    après plusieurs dizaines de Go.
    """

    conn: sqlite3.Connection

    def upsert(self, row: CorpusDownloadRow) -> int:
        """Insère ou met à jour une acquisition, et renvoie son `download_id`.

        Une empreinte déjà connue n'est jamais effacée par une écriture qui n'en porte pas :
        `sha256` n'est calculable gratuitement que lors d'un téléchargement complet.
        """
        cursor = self.conn.execute(
            "INSERT INTO corpus_downloads"
            " (opus_corpus, opus_version, language, url, archive_path, sha256, status)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (opus_corpus, opus_version, language) DO UPDATE SET"
            "     url = coalesce(excluded.url, corpus_downloads.url),"
            "     archive_path = coalesce(excluded.archive_path, corpus_downloads.archive_path),"
            "     sha256 = coalesce(excluded.sha256, corpus_downloads.sha256),"
            "     status = excluded.status"
            " RETURNING download_id",
            (
                row.opus_corpus,
                row.opus_version,
                row.language,
                row.url,
                row.archive_path,
                row.sha256,
                row.status.value,
            ),
        )
        return int(cursor.fetchone()["download_id"])

    def get(
        self,
        *,
        opus_corpus: str,
        opus_version: OpusVersion,
        language: LanguageCode,
    ) -> CorpusDownloadRow | None:
        """Retrouve une acquisition par sa clé naturelle."""
        found = self.conn.execute(
            "SELECT * FROM corpus_downloads"
            " WHERE opus_corpus = ? AND opus_version = ? AND language = ?",
            (opus_corpus, opus_version, language),
        ).fetchone()
        return None if found is None else _to_download_row(found)

    def mark(
        self,
        download_id: int,
        status: DownloadStatus,
        *,
        sha256: Sha256 | None = None,
        archive_path: str | None = None,
        verified: bool = False,
    ) -> None:
        """Fait avancer une acquisition.

        Args:
            download_id: acquisition concernée.
            status: nouvel état. ``downloaded`` horodate `downloaded_at`.
            sha256: empreinte, si elle a pu être calculée.
            archive_path: chemin de l'archive obtenue.
            verified: l'archive a été ouverte et ses membres comptés.
        """
        self.conn.execute(
            "UPDATE corpus_downloads SET"
            "     status = ?,"
            "     sha256 = coalesce(?, sha256),"
            "     archive_path = coalesce(?, archive_path),"
            "     downloaded_at = CASE WHEN ? = 'downloaded'"
            "         THEN datetime('now') ELSE downloaded_at END,"
            "     verified_at = CASE WHEN ? THEN datetime('now') ELSE verified_at END"
            " WHERE download_id = ?",
            (status.value, sha256, archive_path, status.value, int(verified), download_id),
        )

    def iter_all(self) -> Iterator[CorpusDownloadRow]:
        """Toutes les acquisitions, de la plus récente à la plus ancienne."""
        for found in self.conn.execute(
            "SELECT * FROM corpus_downloads ORDER BY downloaded_at DESC, download_id DESC"
        ):
            yield _to_download_row(found)


def _to_download_row(row: sqlite3.Row) -> CorpusDownloadRow:
    """Traduit une ligne de `corpus_downloads`."""
    return CorpusDownloadRow(
        download_id=int(row["download_id"]),
        opus_corpus=str(row["opus_corpus"]),
        opus_version=str(row["opus_version"]),
        language=str(row["language"]),
        url=None if row["url"] is None else str(row["url"]),
        archive_path=None if row["archive_path"] is None else str(row["archive_path"]),
        sha256=None if row["sha256"] is None else str(row["sha256"]),
        status=DownloadStatus(row["status"]),
        downloaded_at=None if row["downloaded_at"] is None else str(row["downloaded_at"]),
        verified_at=None if row["verified_at"] is None else str(row["verified_at"]),
    )
