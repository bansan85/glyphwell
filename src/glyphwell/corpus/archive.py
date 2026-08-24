"""Reads the OPUS archive without ever decompressing it.

The zip archive **is** the corpus. It is never extracted: each subtitle is read member by
member, decompressed on the fly by `zipfile`. This saves the forty-odd gigabytes and the
hundreds of thousands of inodes an extraction would cost, and keeps the corpus a single
artifact, verifiable by a single checksum.

Two costs are accepted in exchange:

- `zipfile` loads the entire central directory on open — on the order of 150 MB for
  400,000 members. That is the price of direct access to any given member.
- Concurrent reads on the same handle serialize. The search engine therefore opens
  **one `CorpusArchive` per thread**, never a shared handle.
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
"""Number of member names collected by `CorpusArchive.summarize`.

Enough to confirm the internal layout at a glance, too few to flood the output.
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveMember:
    """A member of the archive, described without being read.

    Attributes:
        rel_path: name of the member, which is also its opening key. The zip format
            mandates the ``/`` separator: no normalization is applied, or the name would
            stop being directly usable by `CorpusArchive.open_member`.
        size: decompressed size, in bytes.
        compressed_size: size stored in the archive, in bytes.
    """

    rel_path: str
    size: int
    compressed_size: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ArchiveSummary:
    """What a walk of the central directory learns about the archive's contents.

    Discarded members fall into two categories, because they don't carry the same meaning.
    OPUS archives ship service files at their root (``INFO``, ``README``, ``LICENSE``):
    with no extension, they cannot carry subtitles, and flagging them on every download
    would teach nothing. A member *with* an unexpected extension, on the other hand — a
    ``.xml.gz``, a ``.bz2`` — would be text we don't know how to read: that one must be
    visible.

    Attributes:
        subtitle_count: members kept as subtitles.
        metadata_count: extensionless service files at the archive root.
        unexpected_count: members carrying an extension foreign to `SUBTITLE_SUFFIXES`.
            Should be zero; any other value signals that this constant has stopped
            describing the archive.
        samples: first subtitle names, to confirm the layout.
        unexpected_samples: first discarded names, for diagnosis.
    """

    subtitle_count: int
    metadata_count: int
    unexpected_count: int
    samples: tuple[str, ...]
    unexpected_samples: tuple[str, ...]


class CorpusArchive:
    """Read-only access to the corpus archive, member by member.

    Used as a context manager::

        with CorpusArchive(path) as archive:
            for member in archive.iter_members():
                ...

    One handle per thread (see the module docstring).
    """

    __slots__ = ("_path", "_zip")

    def __init__(self, path: Path) -> None:
        """Opens the archive.

        Args:
            path: path to the downloaded zip archive.

        Raises:
            CorpusError: archive missing, truncated, or unreadable.
        """
        if not path.is_file():
            message = f"archive not found: {path}. Run `glyphwell corpus fetch` first."
            raise CorpusError(message)

        # `is_zipfile` only reads the end of the file: the check stays instant on 30 GB, and
        # it's what distinguishes a truncated archive from a complete one.
        if not zipfile.is_zipfile(path):
            message = (
                f"{path} is not a usable zip archive — incomplete or corrupted download."
                " Rerun `glyphwell corpus fetch --force`."
            )
            raise CorpusError(message)

        try:
            self._zip = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile) as exc:
            message = f"unreadable archive: {path} ({exc})"
            raise CorpusError(message) from exc

        self._path = path
        _log.debug("archive opened: %s", path)

    @property
    def path(self) -> Path:
        """Path to the opened archive."""
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
        """Closes the archive. Idempotent."""
        self._zip.close()

    def iter_members(self) -> Iterator[ArchiveMember]:
        """Yields subtitle members, in central directory order.

        Generator: the archive holds hundreds of thousands of members. Directories and
        unexpected suffixes are discarded — `summarize` is the one that counts them.

        Yields:
            One descriptor per subtitle.
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
        """Walks the central directory and describes what the archive contains.

        A single pass, without reading a single byte of content. This is what lets
        ``corpus fetch`` confirm the actual internal layout and flag an unexpected member
        instead of silently absorbing it.

        Args:
            sample_size: number of names collected per category.

        Returns:
            The counts and the samples.
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
                # No extension: a service file, not compressed text.
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
        """Opens a member for reading, decompressed on the fly.

        Nothing is written to disk and the member is not loaded into memory: the returned
        stream is consumed as it is read.

        Args:
            rel_path: name of the member, as carried by `ArchiveMember.rel_path`.

        Returns:
            A binary stream, to be closed by the caller.

        Raises:
            CorpusError: missing member in the archive, or corrupted data.
        """
        try:
            return self._zip.open(rel_path)
        except KeyError as exc:
            message = f"missing member in {self._path.name}: {rel_path}"
            raise CorpusError(message) from exc
        except (OSError, zipfile.BadZipFile) as exc:
            message = f"unreadable member in {self._path.name}: {rel_path} ({exc})"
            raise CorpusError(message) from exc
