"""Empreintes de fichiers.

La clé de fraîcheur d'un sous-titre est ``(opus_version, sha256)`` : c'est cette empreinte
qui décide si les résultats d'un fichier doivent être invalidés.
"""

import hashlib
from pathlib import Path
from typing import Final

from glyphwell.types import Sha256

__all__ = ["DEFAULT_CHUNK_SIZE", "sha256_file"]

DEFAULT_CHUNK_SIZE: Final = 1 << 20
"""1 Mio : le corpus compte des centaines de milliers de fichiers, on ne les charge pas."""


def sha256_file(path: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Sha256:
    """Calcule le SHA-256 d'un fichier par blocs.

    Args:
        path: fichier à hacher.
        chunk_size: taille de lecture, en octets.

    Returns:
        L'empreinte en hexadécimal minuscule.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
