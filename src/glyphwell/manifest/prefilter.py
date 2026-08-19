"""Pré-filtre textuel appliqué avant tout appel au modèle.

Un appel LLM coûte des ordres de grandeur de plus qu'une recherche de sous-chaîne. Sur des
centaines de milliers de sous-titres, écarter localement les fenêtres manifestement hors
sujet est le principal levier sur la durée d'une recherche.

Le pré-filtre est volontairement grossier : il ne doit jamais écarter une fenêtre que le
modèle aurait retenue. En cas de doute, laisser passer.

STATUT : stubs, hors objet valeur.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from glyphwell.manifest.model import PrefilterConfig

__all__ = ["Prefilter"]


@dataclass(frozen=True, slots=True)
class Prefilter:
    """Pré-filtre compilé, réutilisable sur toutes les fenêtres d'une recherche.

    La compilation des motifs a lieu une fois par recherche, pas une fois par fenêtre.
    """

    config: "PrefilterConfig"

    @classmethod
    def compile(cls, config: "PrefilterConfig") -> Self:
        """Prépare le pré-filtre depuis la configuration du manifeste.

        Raises:
            ManifestError: un motif est une expression régulière invalide.
        """
        raise NotImplementedError

    @property
    def enabled(self) -> bool:
        """Faux quand le mode est ``off`` : l'appelant peut sauter l'évaluation."""
        raise NotImplementedError

    def keeps(self, text: str) -> bool:
        """Indique si la fenêtre doit être soumise au modèle.

        Renvoie toujours vrai quand le pré-filtre est désactivé.
        """
        raise NotImplementedError
