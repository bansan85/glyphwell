"""Accès au serveur Ollama.

L'appel est exposé derrière un `Protocol` : le moteur de recherche ne dépend pas d'Ollama,
et les tests injectent un client déterministe sans faire tourner de modèle.

STATUT : stubs, hors objet valeur.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from glyphwell.types import JsonObject, JsonValue

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["Completion", "LlmClient", "OllamaClient"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Completion:
    """Réponse du modèle pour une fenêtre.

    Attributes:
        text: réponse brute, conservée telle quelle pour le diagnostic.
        payload: réponse décodée et validée contre le schéma du manifeste, ou `None` en
            sortie texte.
        model: modèle ayant réellement répondu, tel que rapporté par le serveur.
        latency_ms: durée de l'appel, utile pour estimer le reste d'une recherche.
    """

    text: str
    payload: JsonObject | None
    model: str
    latency_ms: int


class LlmClient(Protocol):
    """Contrat minimal attendu par le moteur de recherche."""

    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: "Mapping[str, JsonValue] | None" = None,
        json_schema: "Mapping[str, JsonValue] | None" = None,
    ) -> Completion:
        """Soumet une fenêtre au modèle et renvoie sa réponse."""
        ...


@dataclass(frozen=True, slots=True, kw_only=True)
class OllamaClient:
    """`LlmClient` adossé au serveur Ollama.

    `json_schema` est transmis au serveur pour contraindre la génération, puis la réponse
    est **revérifiée côté client** : la contrainte réduit les écarts, elle ne les élimine
    pas.
    """

    host: str = "http://localhost:11434"
    timeout: float = 300.0
    max_retries: int = 3

    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: "Mapping[str, JsonValue] | None" = None,
        json_schema: "Mapping[str, JsonValue] | None" = None,
    ) -> Completion:
        """Voir `LlmClient.complete`.

        Raises:
            OllamaError: serveur injoignable, modèle absent, ou échec après `max_retries`.
            ModelOutputError: réponse non conforme au schéma demandé.
        """
        raise NotImplementedError

    def ensure_model(self, model: str) -> None:
        """Vérifie que le modèle est disponible localement avant de lancer une recherche.

        Échouer ici évite de découvrir l'absence du modèle après avoir parcouru le corpus.

        Raises:
            OllamaError: serveur injoignable ou modèle introuvable.
        """
        raise NotImplementedError
