"""File checksums.

The freshness key of a subtitle is ``(opus_version, sha256)``: this checksum is what
decides whether a file's results must be invalidated.
"""

import hashlib
from pathlib import Path
from typing import IO, Final

from glyphwell.types import Sha256

__all__ = ["DEFAULT_CHUNK_SIZE", "sha256_file", "sha256_stream"]

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
    with path.open("rb") as handle:
        return sha256_stream(handle, chunk_size=chunk_size)


def sha256_stream(stream: IO[bytes], *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> Sha256:
    """Computes the SHA-256 of an already-open binary stream, in blocks.

    Used for archive members, which are never written to disk: the caller owns
    `stream` and is responsible for closing it (`CorpusArchive.open_member`'s contract).

    Args:
        stream: binary stream to hash, from the current position onward.
        chunk_size: read size, in bytes.

    Returns:
        The checksum in lowercase hexadecimal.
    """
    digest = hashlib.sha256()
    while chunk := stream.read(chunk_size):
        digest.update(chunk)
    return digest.hexdigest()
