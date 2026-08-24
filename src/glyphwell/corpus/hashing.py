"""File checksums.

The freshness key of a subtitle is ``(opus_version, sha256)``: this checksum is what
decides whether a file's results must be invalidated.
"""

import hashlib
from pathlib import Path
from typing import Final

from glyphwell.types import Sha256

__all__ = ["DEFAULT_CHUNK_SIZE", "sha256_file"]

DEFAULT_CHUNK_SIZE: Final = 1 << 20
"""1 MiB: the corpus holds hundreds of thousands of files, we don't load them whole."""


def sha256_file(path: Path, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Sha256:
    """Computes the SHA-256 of a file in blocks.

    Args:
        path: file to hash.
        chunk_size: read size, in bytes.

    Returns:
        The checksum in lowercase hexadecimal.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
