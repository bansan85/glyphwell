"""Lecture des fichiers de sous-titres OPUS au format ``raw``.

Un fichier contient une suite de balises ``<s id="...">`` portant le texte non tokenisé,
entrecoupées de balises ``<time>`` qui donnent les repères temporels. Deux précautions :

* la lecture est **incrémentale** (``iterparse``) et le générateur libère les éléments au
  fur et à mesure — un sous-titre peut compter des dizaines de milliers de phrases ;
* les fichiers ne sont pas toujours bien formés, d'où ``lxml`` en mode ``recover``.

STATUT : stubs, hors objet valeur.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from glyphwell.types import SentenceId

__all__ = ["Sentence", "count_sentences", "iter_sentences"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Sentence:
    """Une phrase du sous-titre.

    Attributes:
        index: position dans le flux, à partir de 0. **Fait autorité pour la reprise** :
            contrairement à `id`, elle est toujours contiguë et comparable.
        id: attribut ``id`` de la balise ``<s>``, conservé pour la traçabilité. Opaque :
            ordonné, mais pas nécessairement contigu ni purement numérique.
        text: texte de la phrase, espaces normalisés.
        start: horodatage d'entrée le plus proche (``<time value="...">``), si connu.
        end: horodatage de sortie le plus proche, si connu.
    """

    index: int
    id: SentenceId
    text: str
    start: str | None = None
    end: str | None = None


def iter_sentences(path: Path, *, start_index: int = 0) -> Iterator[Sentence]:
    """Produit les phrases d'un fichier de sous-titre, dans l'ordre du document.

    `start_index` permet de reprendre un fichier sans réanalyser son début : les phrases
    précédentes sont traversées mais pas émises. Le fichier est relu depuis le début — c'est
    peu coûteux comparé à un appel LLM, et cela évite de dépendre d'un offset d'octets qui
    serait invalidé par le moindre changement de contenu.

    Args:
        path: fichier ``.xml`` ou ``.xml.gz`` du corpus.
        start_index: première position à émettre.

    Yields:
        Les phrases à partir de `start_index`.

    Raises:
        CorpusReadError: fichier illisible ou irrécupérablement mal formé.
    """
    raise NotImplementedError


def count_sentences(path: Path) -> int:
    """Compte les phrases d'un fichier, sans conserver leur texte.

    Sert à renseigner ``subtitle_files.sentence_count`` et à afficher une progression.

    Raises:
        CorpusReadError: fichier illisible.
    """
    raise NotImplementedError
