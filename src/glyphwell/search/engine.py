"""Moteur de recherche : boucle d'exécution, concurrence, arrêt propre.

Assemble les autres briques — planner, lecteur XML, chunker, pré-filtre, client LLM,
checkpoint — et rien de plus. Toute la logique de correction de la reprise vit dans
`glyphwell.search.checkpoint` ; ce module se contente de l'appeler dans le bon ordre.

Deux points d'attention pour l'implémentation :

* **Concurrence.** Les appels au modèle partent en parallèle (`Settings.concurrency`), mais
  les écritures SQLite restent sérialisées : une seule transaction par fenêtre, jamais deux
  simultanées sur le même fichier.
* **Arrêt propre.** Un SIGINT laisse la fenêtre en cours se terminer et committer, puis passe
  la recherche en `paused`. Un fichier ne doit jamais rester en `in_progress` avec un curseur
  en avance sur les résultats réellement enregistrés.

STATUT : stubs, hors objet valeur.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlite3

    from glyphwell.config import Settings
    from glyphwell.manifest.loader import LoadedManifest
    from glyphwell.ollama.client import LlmClient

__all__ = ["SearchEngine", "SearchOutcome"]


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchOutcome:
    """Bilan d'une exécution ou d'une reprise."""

    run_id: int
    files_done: int
    chunks_done: int
    chunks_skipped: int
    """Fenêtres écartées par le pré-filtre, donc sans appel au modèle."""
    matches: int
    interrupted: bool
    """Vrai si l'exécution s'est arrêtée sur demande : la recherche est reprenable."""


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchEngine:
    """Exécute une recherche décrite par un manifeste."""

    conn: "sqlite3.Connection"
    client: "LlmClient"
    settings: "Settings"

    def start(self, manifest: "LoadedManifest", *, limit: int | None = None) -> SearchOutcome:
        """Crée une recherche, construit sa file, puis l'exécute.

        Si une recherche existe déjà pour ce hash de manifeste et n'est pas terminée, elle
        est reprise au lieu d'être dupliquée.

        Args:
            manifest: manifeste validé.
            limit: nombre maximal de fichiers à traiter, pour un essai.

        Raises:
            SearchError: file vide, ou corpus non indexé.
            OllamaError: modèle indisponible — vérifié avant de parcourir le corpus.
        """
        raise NotImplementedError

    def resume(self, run_id: int, *, limit: int | None = None) -> SearchOutcome:
        """Reprend une recherche interrompue.

        Le manifeste est relu depuis `runs.manifest_snapshot`, pas depuis le disque : une
        reprise utilise exactement le prompt et le fenêtrage du lancement initial, même si le
        fichier a été modifié depuis.

        Raises:
            SearchError: recherche inconnue ou déjà terminée.
        """
        raise NotImplementedError

    def process_file(self, run_id: int, file_id: int) -> int:
        """Traite un fichier depuis son curseur et renvoie le nombre de fenêtres committées.

        Le fichier est relu depuis le début et les phrases déjà traitées sont traversées sans
        être émises : coût négligeable devant un appel au modèle, et aucune dépendance à un
        offset d'octets que le moindre changement de contenu invaliderait.
        """
        raise NotImplementedError

    def request_stop(self) -> None:
        """Demande l'arrêt à la prochaine frontière de fenêtre.

        Appelé depuis le gestionnaire de SIGINT. Ne coupe jamais un appel en cours : la
        fenêtre se termine, committe, et l'arrêt intervient ensuite.
        """
        raise NotImplementedError
