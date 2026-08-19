"""Validation des réponses du modèle et export des résultats.

La contrainte de schéma envoyée à Ollama réduit les écarts mais ne les élimine pas : la
réponse est donc revérifiée ici contre le JSON Schema du manifeste avant d'être écrite.

STATUT : stubs, hors objet valeur.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from glyphwell.types import JsonObject

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Mapping
    from pathlib import Path

    from glyphwell.manifest.model import OutputConfig
    from glyphwell.metadata.resolver import TitleProvider

__all__ = ["ExportFormat", "ValidatedOutput", "export_run", "validate_output"]


class ExportFormat(StrEnum):
    """Formats d'export disponibles."""

    JSONL = "jsonl"
    CSV = "csv"


@dataclass(frozen=True, slots=True, kw_only=True)
class ValidatedOutput:
    """Réponse du modèle après vérification.

    Attributes:
        payload: objet JSON conforme au schéma, ou `None` en sortie texte.
        matched: valeur du champ désigné par ``match_when``. Vrai par défaut quand le
            manifeste n'en désigne aucun.
    """

    payload: JsonObject | None
    matched: bool


def validate_output(raw: str, *, output: "OutputConfig", match_when: str | None) -> ValidatedOutput:
    """Décode et valide la réponse brute du modèle.

    Args:
        raw: texte renvoyé par le modèle.
        output: configuration de sortie du manifeste.
        match_when: nom du champ booléen déterminant la correspondance.

    Returns:
        La réponse validée.

    Raises:
        ModelOutputError: JSON illisible, non conforme au schéma, ou champ `match_when`
            absent ou non booléen.
    """
    raise NotImplementedError


def export_run(
    conn: "sqlite3.Connection",
    *,
    run_id: int,
    dest: "Path",
    export_format: ExportFormat,
    titles: "TitleProvider | None" = None,
    matched_only: bool = True,
) -> int:
    """Écrit les résultats d'une recherche dans un fichier et renvoie le nombre de lignes.

    Les titres sont résolus au moment de l'export, pas stockés dans `results` : un
    ré-import des datasets IMDb améliore ainsi les exports suivants sans retoucher les
    résultats.

    Args:
        conn: connexion à la base.
        run_id: recherche à exporter.
        dest: fichier de sortie.
        export_format: format d'écriture.
        titles: source de titres, pour enrichir chaque ligne.
        matched_only: n'exporter que les correspondances.

    Raises:
        SearchError: recherche inconnue.
        OSError: écriture impossible.
    """
    raise NotImplementedError


def summary(conn: "sqlite3.Connection", run_id: int) -> "Mapping[str, int]":
    """Compteurs d'une recherche, pour ``search status``."""
    raise NotImplementedError
