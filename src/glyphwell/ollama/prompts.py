"""Rendu des gabarits de prompt du manifeste.

Substitution volontairement minimale — ``{{ nom }}`` remplacé par sa valeur — sans moteur de
template complet : un manifeste ne doit pas pouvoir exécuter de code, et une syntaxe réduite
reste lisible dans un YAML.

STATUT : stubs, hors objet valeur.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from glyphwell.types import ImdbId

if TYPE_CHECKING:
    from collections.abc import Mapping

    from glyphwell.corpus.chunker import Chunk
    from glyphwell.metadata.resolver import Title

__all__ = ["PLACEHOLDERS", "PromptContext", "render", "render_context"]

PLACEHOLDERS: Final = (
    "title",
    "year",
    "imdb_id",
    "first_id",
    "last_id",
    "chunk",
)
"""Substitutions reconnues dans ``prompt.system`` et ``prompt.user``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class PromptContext:
    """Valeurs injectées dans un gabarit pour une fenêtre donnée."""

    title: str
    year: int | None
    imdb_id: ImdbId
    first_id: str
    last_id: str
    chunk: str

    def as_mapping(self) -> "Mapping[str, str]":
        """Convertit le contexte en substitutions textuelles.

        Les valeurs absentes deviennent une chaîne vide : un prompt ne doit pas contenir le
        mot ``None``.
        """
        raise NotImplementedError


def render_context(*, chunk: "Chunk", title: "Title | None", imdb_id: ImdbId) -> PromptContext:
    """Assemble le contexte d'une fenêtre.

    `title` peut être `None` quand les datasets IMDb ne connaissent pas l'identifiant : le
    libellé retombe alors sur l'identifiant lui-même, et la recherche continue.
    """
    raise NotImplementedError


def render(template: str, context: PromptContext) -> str:
    """Substitue les ``{{ placeholders }}`` d'un gabarit.

    Args:
        template: gabarit issu du manifeste.
        context: valeurs de la fenêtre courante.

    Returns:
        Le prompt prêt à être envoyé.

    Raises:
        ManifestError: le gabarit référence un placeholder inconnu — mieux vaut le signaler
            que d'envoyer un prompt tronqué à des milliers de fenêtres.
    """
    raise NotImplementedError
