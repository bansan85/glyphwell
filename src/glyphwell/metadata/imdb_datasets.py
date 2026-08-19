"""Datasets IMDb officiels — source primaire des titres.

Deux fichiers suffisent :

* ``title.basics.tsv.gz`` : type, titre, année, durée, flag adulte, genres ;
* ``title.episode.tsv.gz`` : rattachement d'un épisode à sa série, saison, numéro.

Ils sont **indexés par ``tconst``**, exactement l'identifiant que porte l'arborescence du
corpus OPUS : la jointure est directe, hors-ligne, et ne consomme aucune clé API. C'est la
seule source de métadonnées du projet.

Piège du format : la valeur nulle est la chaîne littérale ``\\N``, pas une chaîne vide.

STATUT : stubs, hors constantes.
"""

import sqlite3
from collections.abc import Iterator, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Final

__all__ = [
    "BASE_URL",
    "NULL_MARKER",
    "ImdbDataset",
    "download",
    "import_basics",
    "import_episodes",
    "iter_rows",
]

BASE_URL: Final = "https://datasets.imdbws.com/"
"""Les datasets non commerciaux IMDb, republiés quotidiennement."""

NULL_MARKER: Final = r"\N"
"""Marqueur de valeur absente dans les TSV IMDb. À distinguer de la chaîne vide."""


class ImdbDataset(StrEnum):
    """Datasets utilisés. La valeur est le nom de fichier, donc aussi le suffixe de l'URL."""

    BASICS = "title.basics.tsv.gz"
    EPISODE = "title.episode.tsv.gz"

    @property
    def url(self) -> str:
        """URL de téléchargement du dataset."""
        return f"{BASE_URL}{self.value}"


def download(dataset: ImdbDataset, *, dest_dir: Path, force: bool = False) -> Path:
    """Télécharge un dataset et renvoie le chemin du fichier local.

    Args:
        dataset: dataset visé.
        dest_dir: répertoire de destination.
        force: re-télécharge même si le fichier existe déjà.

    Returns:
        Le chemin du ``.tsv.gz`` local.

    Raises:
        MetadataError: téléchargement impossible.
    """
    raise NotImplementedError


def iter_rows(path: Path) -> Iterator[Mapping[str, str | None]]:
    """Produit les lignes d'un TSV IMDb, en-tête utilisé comme noms de colonnes.

    Générateur : ``title.basics`` compte plus de dix millions de lignes. Les valeurs
    ``\\N`` sont converties en `None`.

    Raises:
        MetadataError: fichier illisible ou en-tête inattendu.
    """
    raise NotImplementedError


def import_basics(conn: sqlite3.Connection, path: Path, *, batch_size: int = 10_000) -> int:
    """Importe ``title.basics`` dans `titles` et renvoie le nombre de lignes écrites.

    Écriture par lots dans une transaction unique par lot : un import interrompu laisse la
    base cohérente et peut être relancé sans dédoublonnage (upsert sur `imdb_id`).

    Raises:
        MetadataError: fichier illisible.
        DatabaseError: échec d'écriture.
    """
    raise NotImplementedError


def import_episodes(conn: sqlite3.Connection, path: Path, *, batch_size: int = 10_000) -> int:
    """Importe ``title.episode`` et complète `titles` (parent, saison, épisode).

    À lancer après `import_basics` : les épisodes doivent déjà exister comme titres.

    Raises:
        MetadataError: fichier illisible.
        DatabaseError: échec d'écriture.
    """
    raise NotImplementedError
