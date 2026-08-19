"""Construction de la file de travail d'une recherche.

Le planner traduit les filtres ``select`` du manifeste en un ensemble de fichiers, puis
matérialise cet ensemble dans `run_files`. Matérialiser la file plutôt que la recalculer à
chaque tour a deux vertus : la progression est mesurable, et une reprise reprend exactement
la même liste même si le corpus a grossi entre-temps.

**L'ordre est un invariant, pas un détail.** Le parcours se fait toujours en
``ORDER BY subtitle_files.rel_path``. Sans cet ordre fixe, `chunk_index` ne désignerait pas
la même plage de phrases d'une exécution à l'autre, et la contrainte d'unicité sur `results`
cesserait de garantir l'idempotence.

STATUT : stubs, hors objet valeur.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

    from glyphwell.manifest.model import SelectConfig

__all__ = ["PlannedFile", "enqueue", "iter_work", "plan_size"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedFile:
    """Un fichier à traiter, avec ce qu'il faut pour le lire et le décrire.

    Regroupe en un objet ce qui viendrait autrement de trois requêtes : le fichier, son
    titre et son curseur.
    """

    file_id: int
    rel_path: str
    imdb_id: str
    sentence_count: int | None
    last_sentence_index: int | None
    chunks_done: int


def enqueue(conn: sqlite3.Connection, *, run_id: int, select: "SelectConfig") -> int:
    """Remplit `run_files` pour une recherche et renvoie le nombre de fichiers ajoutés.

    Idempotent : relançable pour compléter la file d'une recherche existante quand de
    nouveaux fichiers sont apparus au corpus, sans toucher aux fichiers déjà traités.

    Les filtres portant sur le titre exigent que les datasets IMDb aient été importés. Les
    fichiers dont l'identifiant reste non résolu sont écartés, et leur nombre est journalisé
    — un corpus indexé sans métadonnées produirait sinon une file vide sans explication.

    Raises:
        DatabaseError: échec d'écriture.
    """
    raise NotImplementedError


def iter_work(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    limit: int | None = None,
) -> "Iterator[PlannedFile]":
    """Produit les fichiers non terminés, dans l'ordre déterministe du plan.

    Générateur : la file peut compter des centaines de milliers d'entrées.

    Args:
        conn: connexion à la base.
        run_id: recherche concernée.
        limit: arrête après ce nombre de fichiers, pour un essai rapide.

    Yields:
        Les fichiers à traiter, ``ORDER BY rel_path``.
    """
    raise NotImplementedError


def plan_size(conn: sqlite3.Connection, run_id: int) -> tuple[int, int]:
    """Renvoie ``(fichiers terminés, fichiers au plan)`` pour l'affichage de progression."""
    raise NotImplementedError
