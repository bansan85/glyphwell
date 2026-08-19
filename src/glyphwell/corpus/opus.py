"""Acquisition du corpus via `opustools`.

`opustools` expose `OpusGet`, qui interroge l'index OPUS et télécharge les archives. On
cible le corpus ``OpenSubtitles``, une langue unique et le préprocessing ``raw`` : c'est la
seule variante qui conserve le texte non tokenisé, exploitable tel quel par un LLM.

STATUT : stubs, hors constantes.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from glyphwell.types import LanguageCode, OpusVersion, Sha256

__all__ = [
    "DEFAULT_CORPUS",
    "DEFAULT_PREPROCESSING",
    "DEFAULT_VERSION",
    "CorpusDownload",
    "Preprocessing",
    "download_corpus",
    "extract_archive",
    "iter_available_versions",
]

type Preprocessing = Literal["raw", "xml", "mono"]

DEFAULT_CORPUS: Final = "OpenSubtitles"
DEFAULT_VERSION: Final[OpusVersion] = "v2018"
DEFAULT_PREPROCESSING: Final[Preprocessing] = "raw"
"""``raw`` conserve le texte non tokenisé ; ``xml`` le découpe en balises ``<w>``."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusDownload:
    """Résultat d'un téléchargement de corpus."""

    corpus: str
    version: OpusVersion
    language: LanguageCode
    archive_path: Path
    sha256: Sha256 | None
    url: str | None


def iter_available_versions(corpus: str = DEFAULT_CORPUS) -> Iterator[OpusVersion]:
    """Liste les versions disponibles d'un corpus, de la plus récente à la plus ancienne.

    Alimente la détection de fraîcheur : une release supérieure à celle déjà en base
    signifie que des sous-titres plus récents sont disponibles.

    Raises:
        MetadataError: l'index OPUS est injoignable ou illisible.
    """
    raise NotImplementedError


def download_corpus(
    *,
    dest_dir: Path,
    corpus: str = DEFAULT_CORPUS,
    version: OpusVersion = DEFAULT_VERSION,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    force: bool = False,
) -> CorpusDownload:
    """Télécharge l'archive monolingue d'un corpus OPUS.

    Args:
        dest_dir: répertoire où déposer l'archive.
        corpus: nom du corpus OPUS.
        version: release visée.
        language: code de langue.
        preprocessing: variante de préprocessing.
        force: re-télécharge même si l'archive est déjà présente.

    Returns:
        La description de l'archive obtenue.

    Raises:
        CorpusError: téléchargement impossible ou archive incomplète.
    """
    raise NotImplementedError


def extract_archive(archive_path: Path, *, dest_dir: Path, force: bool = False) -> int:
    """Extrait une archive de corpus et renvoie le nombre de fichiers écrits.

    L'extraction préserve l'arborescence d'origine (``<langue>/<année>/<imdb>/``), dont
    dépend `glyphwell.corpus.layout`. Les entrées sortant du répertoire cible sont refusées.

    Raises:
        CorpusError: archive corrompue, ou entrée au chemin suspect.
    """
    raise NotImplementedError
