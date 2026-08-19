"""Curseur de reprise.

Module le plus critique du projet : c'est ici que la promesse « reprendre à la ligne en
cours » se traduit en écritures SQLite.

Deux invariants gouvernent tout le module :

1. **Une transaction par fenêtre.** `commit_chunk` écrit le résultat *et* l'avancement du
   curseur dans la même transaction. Un crash ne peut donc ni perdre un résultat déjà
   produit, ni faire avancer le curseur au-delà de ce qui a été enregistré.
2. **Idempotence.** L'insertion du résultat est un ``INSERT OR IGNORE`` sur
   ``UNIQUE(run_id, file_id, chunk_index)`` : rejouer une fenêtre après une interruption ne
   crée pas de doublon. Le doublon est le cas normal, pas une erreur.

STATUT : stubs, hors objet valeur.
"""

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from glyphwell.types import JsonObject

if TYPE_CHECKING:
    from glyphwell.corpus.chunker import Chunk

__all__ = ["Checkpoint", "commit_chunk", "load_checkpoint", "resume_position"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Checkpoint:
    """Où en est un fichier dans une recherche.

    Attributes:
        run_id: recherche concernée.
        file_id: fichier concerné.
        last_sentence_index: position de la dernière phrase traitée, ou `None` si le fichier
            n'a pas encore été entamé. **Fait autorité** pour la reprise.
        last_sentence_id: attribut ``<s id>`` correspondant, informatif.
        chunks_done: nombre de fenêtres déjà committées, qui donne le prochain
            `Chunk.index`.
    """

    run_id: int
    file_id: int
    last_sentence_index: int | None
    last_sentence_id: str | None
    chunks_done: int

    @property
    def started(self) -> bool:
        """Vrai si au moins une fenêtre a été committée pour ce fichier."""
        return self.last_sentence_index is not None


def load_checkpoint(conn: sqlite3.Connection, *, run_id: int, file_id: int) -> Checkpoint | None:
    """Lit le curseur d'un fichier, ou `None` s'il n'est pas dans la file de cette recherche."""
    raise NotImplementedError


def resume_position(checkpoint: Checkpoint | None, *, size: int, overlap: int) -> tuple[int, int]:
    """Calcule où reprendre la lecture d'un fichier.

    Args:
        checkpoint: curseur courant, ou `None` pour un fichier neuf.
        size: taille de fenêtre du manifeste.
        overlap: recouvrement du manifeste.

    Returns:
        Le couple ``(start_index, start_chunk_index)`` : première phrase à émettre, et
        numéro à donner à la première fenêtre produite. Les deux valeurs doivent rester
        cohérentes, sinon `chunk_index` cesserait de désigner la même plage de phrases
        qu'au premier passage et la contrainte d'unicité perdrait son sens.
    """
    raise NotImplementedError


def commit_chunk(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    file_id: int,
    chunk: "Chunk",
    matched: bool,
    payload: JsonObject | None,
    model: str,
    latency_ms: int | None,
) -> bool:
    """Enregistre le résultat d'une fenêtre et avance le curseur, en une transaction.

    Returns:
        Vrai si un résultat a été inséré, faux si la fenêtre était déjà enregistrée — ce qui
        arrive normalement lors d'une reprise et n'est pas une erreur. Dans les deux cas le
        curseur est avancé.

    Raises:
        DatabaseError: échec d'écriture. La transaction est alors annulée : le curseur reste
            sur la dernière fenêtre réellement enregistrée.
    """
    raise NotImplementedError
