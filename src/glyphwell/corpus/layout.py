"""Arborescence interne de l'archive OPUS OpenSubtitles.

Nom des membres du zip, préfixe compris :

    <corpus>/<preprocessing>/<langue>/<année>/<imdb_id>/<opensubtitles_file_id>.xml
    OpenSubtitles/raw/fr/2022/1596342/1957893755.xml

L'identifiant IMDb y apparaît **nu** (``1596342``), pas sous sa forme canonique
(``tt1596342``). Toute la normalisation est concentrée ici.

L'archive n'étant jamais décompressée, ces chemins ne désignent aucun fichier du disque :
ce sont les clés d'ouverture de `glyphwell.corpus.archive.CorpusArchive`.

STATUT : stubs, hors constantes.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from glyphwell.types import ImdbId, LanguageCode, OpenSubtitlesFileId

if TYPE_CHECKING:
    from glyphwell.corpus.archive import CorpusArchive

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

SUBTITLE_SUFFIXES: Final = (".xml",)
"""Extensions des membres de sous-titres dans l'archive.

Les membres sont des XML simples : le zip est le seul niveau de compression. Tout membre
d'un autre suffixe est compté et signalé par ``corpus fetch`` plutôt qu'absorbé
silencieusement — ce serait le signe que cette hypothèse a cessé d'être vraie.
"""

_IMDB_NUMERIC = re.compile(r"^\d+$")


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusEntry:
    """Un fichier de sous-titre localisé dans l'arborescence du corpus.

    Attributes:
        rel_path: nom du membre dans l'archive, préfixe compris, séparateurs ``/``.
            C'est la clé naturelle du fichier en base, la clé de tri de la file de
            travail, et la clé d'ouverture du membre.
        language: code de langue OPUS.
        year: année portée par l'arborescence, `None` si le répertoire n'est pas une année.
        imdb_id: identifiant canonique, préfixe ``tt`` inclus.
        opensubtitles_file_id: identifiant du sous-titre sur opensubtitles.org.
    """

    rel_path: str
    language: LanguageCode
    year: int | None
    imdb_id: ImdbId
    opensubtitles_file_id: OpenSubtitlesFileId


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
        rel_path: nom d'un membre de l'archive, par exemple
            ``OpenSubtitles/raw/en/1999/0133093/3660124.xml``.

    Returns:
        L'entrée décrite par ce chemin.

    Raises:
        CorpusLayoutError: le chemin ne respecte pas l'arborescence attendue.
    """
    raise NotImplementedError


def iter_corpus(
    archive: "CorpusArchive",
    *,
    language: LanguageCode | None = None,
) -> Iterator[CorpusEntry]:
    """Parcourt l'archive et produit une entrée par membre de sous-titre.

    Générateur : l'archive compte des centaines de milliers de membres et ne doit jamais
    être matérialisée en mémoire. Les noms qui ne respectent pas l'arborescence sont
    journalisés puis ignorés, plutôt que d'interrompre un scan de plusieurs minutes.

    Args:
        archive: archive ouverte, jamais décompressée.
        language: restreint le parcours à une langue, ou toutes si `None`.

    Yields:
        Les entrées rencontrées, dans un ordre non garanti — c'est le planner qui trie.
    """
    raise NotImplementedError
