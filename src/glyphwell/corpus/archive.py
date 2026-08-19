"""Lecture de l'archive OPUS, sans jamais la décompresser.

L'archive zip **est** le corpus. Elle n'est pas extraite : chaque sous-titre est lu membre
par membre, décompressé à la volée par `zipfile`. On économise ainsi la quarantaine de Go
et les centaines de milliers d'inodes qu'une extraction coûterait, et le corpus reste un
artefact unique, vérifiable par une seule empreinte.

Deux coûts sont assumés en contrepartie :

- `zipfile` charge l'intégralité du répertoire central à l'ouverture — de l'ordre de
  150 Mo pour 400 000 membres. C'est le prix de l'accès direct à un membre quelconque.
- Les lectures concurrentes sur un même handle se sérialisent. Le moteur de recherche
  ouvre donc **un `CorpusArchive` par thread**, jamais un handle partagé.
"""

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import IO, Final, Self

from glyphwell.corpus.layout import SUBTITLE_SUFFIXES
from glyphwell.errors import CorpusError
from glyphwell.logging import get_logger

__all__ = ["ArchiveMember", "ArchiveSummary", "CorpusArchive"]

_log = get_logger(__name__)

DEFAULT_SAMPLE_SIZE: Final = 3
"""Nombre de noms de membres relevés par `CorpusArchive.summarize`.

Assez pour confirmer l'arborescence interne d'un coup d'œil, trop peu pour noyer la sortie.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveMember:
    """Un membre de l'archive, décrit sans être lu.

    Attributes:
        rel_path: nom du membre, qui est aussi sa clé d'ouverture. Le format zip impose le
            séparateur ``/`` : aucune normalisation n'est appliquée, sans quoi le nom
            cesserait d'être utilisable tel quel par `CorpusArchive.open_member`.
        size: taille décompressée, en octets.
        compressed_size: taille stockée dans l'archive, en octets.
    """

    rel_path: str
    size: int
    compressed_size: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveSummary:
    """Ce qu'un parcours du répertoire central apprend du contenu de l'archive.

    Les membres écartés sont répartis en deux catégories, parce qu'ils n'ont pas le même
    sens. Les archives OPUS embarquent des fichiers de service à leur racine (``INFO``,
    ``README``, ``LICENSE``) : sans extension, ils ne peuvent pas porter de sous-titres, et
    les signaler à chaque téléchargement n'apprendrait rien. Un membre *avec* une extension
    inattendue, en revanche — un ``.xml.gz``, un ``.bz2`` — serait du texte qu'on ne sait
    pas lire : celui-là doit se voir.

    Attributes:
        subtitle_count: membres retenus comme sous-titres.
        metadata_count: fichiers de service sans extension, à la racine de l'archive.
        unexpected_count: membres portés par une extension étrangère à
            `SUBTITLE_SUFFIXES`. Doit valoir zéro ; toute autre valeur signale que cette
            constante a cessé de décrire l'archive.
        samples: premiers noms de sous-titres, pour confirmer l'arborescence.
        unexpected_samples: premiers noms écartés, pour diagnostiquer.
    """

    subtitle_count: int
    metadata_count: int
    unexpected_count: int
    samples: tuple[str, ...]
    unexpected_samples: tuple[str, ...]


class CorpusArchive:
    """Accès en lecture à l'archive du corpus, membre par membre.

    S'utilise comme gestionnaire de contexte::

        with CorpusArchive(path) as archive:
            for member in archive.iter_members():
                ...

    Un handle par thread (cf. le docstring du module).
    """

    __slots__ = ("_path", "_zip")

    def __init__(self, path: Path) -> None:
        """Ouvre l'archive.

        Args:
            path: chemin de l'archive zip téléchargée.

        Raises:
            CorpusError: archive absente, tronquée ou illisible.
        """
        if not path.is_file():
            message = f"archive introuvable : {path}. Lancer `glyphwell corpus fetch` d'abord."
            raise CorpusError(message)

        # `is_zipfile` ne lit que la fin du fichier : le test reste immédiat sur 30 Go, et
        # c'est lui qui distingue une archive tronquée d'une archive complète.
        if not zipfile.is_zipfile(path):
            message = (
                f"{path} n'est pas une archive zip exploitable — téléchargement incomplet ou"
                " corrompu. Relancer `glyphwell corpus fetch --force`."
            )
            raise CorpusError(message)

        try:
            self._zip = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as exc:
            message = f"archive illisible : {path} ({exc})"
            raise CorpusError(message) from exc

        self._path = path
        _log.debug("archive ouverte : %s", path)

    @property
    def path(self) -> Path:
        """Chemin de l'archive ouverte."""
        return self._path

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Referme l'archive. Idempotent."""
        self._zip.close()

    def iter_members(self) -> Iterator[ArchiveMember]:
        """Produit les membres de sous-titre, dans l'ordre du répertoire central.

        Générateur : l'archive compte des centaines de milliers de membres. Les répertoires
        et les suffixes inattendus sont écartés — c'est `summarize` qui les compte.

        Yields:
            Un descripteur par sous-titre.
        """
        for info in self._zip.infolist():
            if info.is_dir() or not info.filename.endswith(SUBTITLE_SUFFIXES):
                continue
            yield ArchiveMember(
                rel_path=info.filename,
                size=info.file_size,
                compressed_size=info.compress_size,
            )

    def summarize(self, *, sample_size: int = DEFAULT_SAMPLE_SIZE) -> ArchiveSummary:
        """Parcourt le répertoire central et décrit ce que contient l'archive.

        Une seule passe, sans lire le moindre octet de contenu. C'est ce qui permet à
        ``corpus fetch`` de confirmer l'arborescence interne réelle et de signaler un
        membre inattendu au lieu de l'absorber en silence.

        Args:
            sample_size: nombre de noms relevés dans chaque catégorie.

        Returns:
            Le décompte et les échantillons.
        """
        subtitles = 0
        metadata = 0
        unexpected = 0
        samples: list[str] = []
        unexpected_samples: list[str] = []

        for info in self._zip.infolist():
            if info.is_dir():
                continue
            if info.filename.endswith(SUBTITLE_SUFFIXES):
                subtitles += 1
                if len(samples) < sample_size:
                    samples.append(info.filename)
            elif not PurePosixPath(info.filename).suffix:
                # Sans extension : un fichier de service, pas du texte compressé.
                metadata += 1
            else:
                unexpected += 1
                if len(unexpected_samples) < sample_size:
                    unexpected_samples.append(info.filename)

        return ArchiveSummary(
            subtitle_count=subtitles,
            metadata_count=metadata,
            unexpected_count=unexpected,
            samples=tuple(samples),
            unexpected_samples=tuple(unexpected_samples),
        )

    def open_member(self, rel_path: str) -> IO[bytes]:
        """Ouvre un membre en lecture, décompressé à la volée.

        Rien n'est écrit sur le disque et le membre n'est pas chargé en mémoire : le flux
        rendu se consomme au fil de l'eau.

        Args:
            rel_path: nom du membre, tel que porté par `ArchiveMember.rel_path`.

        Returns:
            Un flux binaire, à refermer par l'appelant.

        Raises:
            CorpusError: membre absent de l'archive, ou données corrompues.
        """
        try:
            return self._zip.open(rel_path)
        except KeyError as exc:
            message = f"membre absent de {self._path.name} : {rel_path}"
            raise CorpusError(message) from exc
        except (OSError, zipfile.BadZipFile) as exc:
            message = f"membre illisible dans {self._path.name} : {rel_path} ({exc})"
            raise CorpusError(message) from exc
