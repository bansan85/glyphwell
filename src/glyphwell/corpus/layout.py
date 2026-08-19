"""Arborescence du corpus OPUS OpenSubtitles.

Structure attendue, relative à la racine du corpus extrait :

    <langue>/<année>/<imdb_id>/<opus_file_id>.xml

L'identifiant IMDb y apparaît **nu et zéro-paddé** (``133093``), pas sous sa forme
canonique (``tt0133093``). Toute la normalisation est concentrée ici.

ATTENTION : cette structure est déduite de l'usage, elle n'est pas documentée sur le site
OPUS actuel. C'est la raison pour laquelle elle est isolée derrière deux fonctions et
couverte par un test sur échantillon : si le premier ``corpus fetch`` révèle une autre
disposition, seul ce module change.

STATUT : stubs, hors constantes.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from glyphwell.types import ImdbId, LanguageCode, OpusFileId

__all__ = [
    "IMDB_ID_WIDTH",
    "SUBTITLE_SUFFIXES",
    "CorpusEntry",
    "iter_corpus",
    "normalize_imdb_id",
    "parse_entry",
]

IMDB_ID_WIDTH: Final = 7
"""Largeur minimale de la partie numérique d'un identifiant IMDb : ``tt0133093``.

Les identifiants récents dépassent 7 chiffres et ne sont alors pas paddés du tout.
"""

SUBTITLE_SUFFIXES: Final = (".xml", ".xml.gz")
"""Extensions rencontrées dans le corpus, selon que l'archive a été décompressée ou non."""

_IMDB_NUMERIC = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusEntry:
    """Un fichier de sous-titre localisé dans l'arborescence du corpus.

    Attributes:
        rel_path: chemin relatif à la racine du corpus, séparateurs normalisés en ``/``.
            C'est la clé naturelle du fichier en base et la clé de tri de la file de
            travail.
        language: code de langue OPUS.
        year: année portée par l'arborescence, `None` si le répertoire n'est pas une année.
        imdb_id: identifiant canonique, préfixe ``tt`` inclus.
        opus_file_id: nom du fichier sans extension.
    """

    rel_path: str
    language: LanguageCode
    year: int | None
    imdb_id: ImdbId
    opus_file_id: OpusFileId


def normalize_imdb_id(raw: str) -> ImdbId:
    """Convertit un identifiant IMDb vers sa forme canonique ``tt#######``.

    Accepte la forme nue du corpus (``133093``), déjà préfixée (``tt0133093``), et les
    identifiants plus longs que sept chiffres, qui ne sont pas paddés.

    Args:
        raw: identifiant tel qu'il apparaît dans un chemin ou un dataset.

    Returns:
        L'identifiant canonique.

    Raises:
        CorpusLayoutError: la chaîne n'est pas un identifiant IMDb reconnaissable.
    """
    raise NotImplementedError


def parse_entry(rel_path: Path) -> CorpusEntry:
    """Interprète un chemin relatif du corpus.

    Args:
        rel_path: chemin relatif à la racine du corpus, par exemple
            ``en/1999/0133093/3660124.xml``.

    Returns:
        L'entrée décrite par ce chemin.

    Raises:
        CorpusLayoutError: le chemin ne respecte pas l'arborescence attendue.
    """
    raise NotImplementedError


def iter_corpus(root: Path, *, language: LanguageCode | None = None) -> Iterator[CorpusEntry]:
    """Parcourt le corpus et produit une entrée par fichier de sous-titre.

    Générateur : le corpus compte des centaines de milliers de fichiers et ne doit jamais
    être matérialisé en mémoire. Les chemins qui ne respectent pas l'arborescence sont
    journalisés puis ignorés, plutôt que d'interrompre un scan de plusieurs minutes.

    Args:
        root: racine du corpus extrait.
        language: restreint le parcours à une langue, ou toutes si `None`.

    Yields:
        Les entrées rencontrées, dans un ordre non garanti — c'est le planner qui trie.
    """
    raise NotImplementedError
