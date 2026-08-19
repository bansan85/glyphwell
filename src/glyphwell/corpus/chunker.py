"""Découpage d'un sous-titre en fenêtres glissantes.

Une fenêtre est l'unité d'appel au modèle **et** l'unité de reprise. Le recouvrement évite
qu'un passage à cheval sur deux fenêtres passe inaperçu.

Le découpage doit être **déterministe** : pour un fichier et un ``(size, overlap)`` donnés,
`Chunk.index` désigne toujours la même plage de phrases. C'est ce qui rend la contrainte
``UNIQUE(run_id, file_id, chunk_index)`` de la table `results` utilisable comme garantie
d'idempotence.

STATUT : stubs, hors objet valeur.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from glyphwell.corpus.reader import Sentence

__all__ = ["Chunk", "chunk_count", "iter_chunks"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk:
    """Une fenêtre de phrases consécutives.

    Attributes:
        index: position de la fenêtre dans le fichier, à partir de 0.
        sentences: les phrases de la fenêtre, dans l'ordre. Jamais vide.
    """

    index: int
    sentences: tuple["Sentence", ...]

    @property
    def first(self) -> "Sentence":
        """Première phrase de la fenêtre."""
        return self.sentences[0]

    @property
    def last(self) -> "Sentence":
        """Dernière phrase de la fenêtre. Détermine l'avancement du curseur de reprise."""
        return self.sentences[-1]

    def render(self, *, with_ids: bool = True) -> str:
        """Assemble le texte de la fenêtre pour l'injecter dans le prompt.

        Args:
            with_ids: préfixe chaque ligne de son identifiant de phrase, ce qui permet au
                modèle de citer des repères vérifiables.
        """
        if with_ids:
            return "\n".join(f"[{sentence.id}] {sentence.text}" for sentence in self.sentences)
        return "\n".join(sentence.text for sentence in self.sentences)


def iter_chunks(
    sentences: Iterable["Sentence"],
    *,
    size: int,
    overlap: int,
    start_chunk_index: int = 0,
) -> Iterator[Chunk]:
    """Découpe un flux de phrases en fenêtres glissantes.

    Args:
        sentences: flux de phrases, consommé paresseusement.
        size: nombre de phrases par fenêtre.
        overlap: nombre de phrases répétées d'une fenêtre à la suivante. Doit être
            strictement inférieur à `size`, sinon la fenêtre n'avance pas.
        start_chunk_index: décalage appliqué à `Chunk.index`, pour numéroter correctement
            les fenêtres lors d'une reprise en cours de fichier.

    Yields:
        Les fenêtres successives. La dernière peut compter moins de `size` phrases.

    Raises:
        ValueError: `size` non strictement positif, ou `overlap` hors de ``[0, size)``.
    """
    raise NotImplementedError


def chunk_count(sentence_count: int, *, size: int, overlap: int) -> int:
    """Nombre de fenêtres que produirait un fichier de `sentence_count` phrases.

    Sert à afficher une progression avant d'avoir lu le fichier.

    Raises:
        ValueError: paramètres de fenêtrage invalides.
    """
    raise NotImplementedError
