"""Corpus acquisition via `opustools`.

`opustools` exposes `OpusGet`, which knows the OPUS index's contract: URL shape,
parameters, archive naming. That is the sole reason it is used here — to *find* the
archive. We target the ``OpenSubtitles`` corpus, a single language, and ``raw``
preprocessing: the only variant that keeps the text non-tokenized, usable as-is by an LLM.

The byte transfer itself goes through `httpx`, not `OpusGet.get_files()`. The latter is
unusable on several dozen gigabytes: it has no timeout, cannot resume, swallows
`urllib.error.URLError` to fall back on a mere `print` — and it writes directly under the
final name. A cutoff at 90% would therefore leave a truncated archive indistinguishable
from a complete one. Here, the transfer goes into a ``.part`` file resumed via a ``Range``
header, renamed only once complete.

The archive is never decompressed: see `glyphwell.corpus.archive`.
"""

import hashlib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import httpx
from opustools import OpusGet
from pydantic import BaseModel, ConfigDict, ValidationError

from glyphwell.errors import CorpusError, MetadataError
from glyphwell.logging import get_logger
from glyphwell.types import LanguageCode, OpusVersion, Sha256

__all__ = [
    "DEFAULT_CORPUS",
    "DEFAULT_PREPROCESSING",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VERSION",
    "CorpusDownload",
    "OpusFileRecord",
    "Preprocessing",
    "ProgressCallback",
    "download_corpus",
    "iter_available_versions",
    "resolve_archive",
]

_log = get_logger(__name__)

type Preprocessing = Literal["raw", "xml", "mono"]

type ProgressCallback = Callable[[int, int | None], None]
"""Progress callback: total bytes received, final size or `None` if unknown.

The bytes received include what had already been received on a previous attempt: on a
resume, progress starts from the ``.part`` offset, not from zero.
"""

DEFAULT_CORPUS: Final = "OpenSubtitles"
DEFAULT_VERSION: Final[OpusVersion] = "v2024"
DEFAULT_PREPROCESSING: Final[Preprocessing] = "raw"
"""``raw`` keeps the text non-tokenized; ``xml`` splits it into ``<w>`` tags."""

DEFAULT_TIMEOUT: Final = 60.0
"""Timeout, in seconds, applied per block, not to the whole transfer."""

_PART_SUFFIX: Final = ".part"
_CHUNK_SIZE: Final = 1 << 20
_KIB: Final = 1024
"""The OPUS index expresses `size` in kilobytes (see `OpusGet.format_size`)."""

_OMITTED: Final = ""
"""`OpusGet` does not emit empty parameters, and that is the only way to say "all
values". The "single space" wildcard its code suggests produces ``version=``, which the
online API interprets as "no version": it then returns zero results."""

_SIZE_TOLERANCE: Final = 0.01
"""The size announced by the index is rounded: beyond a 1% gap, we warn."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusDownload:
    """Result of a corpus download."""

    corpus: str
    version: OpusVersion
    language: LanguageCode
    archive_path: Path
    sha256: Sha256 | None
    url: str | None


class OpusFileRecord(BaseModel):
    """A record from the OPUS index.

    `extra="ignore"`, unlike manifests: the API is not under our control, a field added
    upstream must not make a download fail.

    Attributes:
        target: empty for a monolingual archive. This is the discriminant: a request on a
            language also returns the bilingual pairs that contain it.
        size: size in **kilobytes**, rounded.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    corpus: str
    version: OpusVersion
    preprocessing: str
    source: LanguageCode
    target: str
    url: str
    size: int


class _OpusIndex(BaseModel):
    """Envelope of the index response."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    corpora: tuple[OpusFileRecord, ...]


def _make_client(*, timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """Default HTTP client.

    `follow_redirects` is essential: the index returns an object storage URL that
    redirects.
    """
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=timeout),
    )


def _opus_getter(
    *,
    corpus: str | None = None,
    version: str | None = None,
    language: LanguageCode | None = None,
    preprocessing: str | None = None,
) -> OpusGet:
    """Instantiates `OpusGet` without side effects.

    `download_dir` stays the current directory: `OpusGet` creates it if missing, and we
    don't want a mere URL construction to create a directory. Nothing is downloaded by
    this instance — only `url` and `make_file_name` are read.

    Mind the order of `OpusGet`'s parameters: `directory` is the corpus name, `source` the
    language.
    """
    return OpusGet(
        source=language,
        directory=corpus,
        release=version if version is not None else _OMITTED,
        preprocess=preprocessing if preprocessing is not None else _OMITTED,
        download_dir=".",
        suppress_prompts=True,
    )


def _index_url(
    *,
    corpus: str | None = None,
    version: str | None = None,
    language: LanguageCode | None = None,
    preprocessing: str | None = None,
) -> str:
    """OPUS index URL for these criteria."""
    # `OpusGet` builds the URL with a trailing `&`, which its own code strips on call.
    return _opus_getter(
        corpus=corpus,
        version=version,
        language=language,
        preprocessing=preprocessing,
    ).url.removesuffix("&")


def _fetch_records(url: str, *, client: httpx.Client | None = None) -> tuple[OpusFileRecord, ...]:
    """Queries the index and validates its response.

    Raises:
        MetadataError: index unreachable, or response unreadable.
    """
    owned = client is None
    http = client if client is not None else _make_client()
    try:
        response = http.get(url)
        response.raise_for_status()
        # Untyped boundary: `object`, then immediately narrowed by pydantic.
        payload: object = response.json()
    except httpx.HTTPError as exc:
        message = f"OPUS index unreachable ({url}): {exc}"
        raise MetadataError(message) from exc
    except ValueError as exc:
        message = f"unreadable response from the OPUS index ({url}): {exc}"
        raise MetadataError(message) from exc
    finally:
        if owned:
            http.close()

    try:
        index = _OpusIndex.model_validate(payload)
    except ValidationError as exc:
        message = f"unexpected response from the OPUS index ({url}):\n{exc}"
        raise MetadataError(message) from exc

    _log.debug("OPUS index: %d record(s) for %s", len(index.corpora), url)
    return index.corpora


def _version_key(version: OpusVersion) -> tuple[int, ...]:
    """Numeric sort key for a release: ``v2018`` gives ``(2018,)``.

    A non-numeric version gives an empty key, so it sorts last in descending order; the
    caller breaks ties on the string itself.
    """
    parts = version.removeprefix("v").split(".")
    if not all(part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def iter_available_versions(
    corpus: str = DEFAULT_CORPUS,
    *,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    client: httpx.Client | None = None,
) -> Iterator[OpusVersion]:
    """Lists the available versions of a corpus, from newest to oldest.

    Feeds freshness detection: a release newer than the one already in the database means
    newer subtitles are available.

    The language and preprocessing are deliberately fixed. Without them, the index would
    return every language pair of the corpus — for OpenSubtitles, several thousand records
    for information that fits in a few lines.

    Args:
        corpus: name of the OPUS corpus.
        language: language whose releases are wanted.
        preprocessing: preprocessing variant.
        client: HTTP client to reuse, otherwise a throwaway client is created.

    Yields:
        The versions, from newest to oldest.

    Raises:
        MetadataError: the OPUS index is unreachable or unreadable.
    """
    # No `version` parameter: that's what makes the index return every release.
    url = _index_url(corpus=corpus, language=language, preprocessing=preprocessing)
    versions = {record.version for record in _fetch_records(url, client=client)}
    yield from sorted(versions, key=lambda version: (_version_key(version), version), reverse=True)


def resolve_archive(
    *,
    corpus: str = DEFAULT_CORPUS,
    version: OpusVersion = DEFAULT_VERSION,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    client: httpx.Client | None = None,
) -> OpusFileRecord:
    """Finds the monolingual archive matching these criteria in the index.

    Kept separate from `download_corpus` so the caller can announce the URL and size before
    committing to a transfer of several dozen gigabytes.

    Args:
        corpus: name of the OPUS corpus.
        version: targeted release.
        language: language code.
        preprocessing: preprocessing variant.
        client: HTTP client to reuse.

    Returns:
        The monolingual archive record.

    Raises:
        MetadataError: the index is unreachable or unreadable.
        CorpusError: the index offers no archive for these criteria.
    """
    url = _index_url(
        corpus=corpus,
        version=version,
        language=language,
        preprocessing=preprocessing,
    )
    records = _fetch_records(url, client=client)
    # Two families to discard, and the index returns both: bilingual pairs containing the
    # requested language (`target` non-empty), and — in ``raw`` preprocessing — the
    # monolingual archive of *every* language paired with ours. Without the check on
    # `source`, an ``en`` request surfaces some fifty candidates including ``eo`` or
    # ``es``, and whichever comes first would be downloaded.
    monolingual = [record for record in records if not record.target and record.source == language]

    if not monolingual:
        message = (
            f"no monolingual archive {corpus} {version} {language} ({preprocessing})"
            f" in the OPUS index. {_describe(records)}"
        )
        raise CorpusError(message)

    if len(monolingual) > 1:
        _log.warning(
            "%d monolingual archives match; the first one is kept: %s",
            len(monolingual),
            monolingual[0].url,
        )
    return monolingual[0]


def _describe(records: tuple[OpusFileRecord, ...], *, limit: int = 12) -> str:
    """Describes what the index returned, to make the error actionable.

    A broad query returns hundreds of records: we summarize along the two axes the caller
    can act on, version and language.
    """
    if not records:
        return "The index returned no records: check the corpus name."

    versions = sorted({record.version for record in records})
    languages = sorted({record.source for record in records if not record.target})
    shown = ", ".join(languages[:limit])
    suffix = f", ... ({len(languages)} total)" if len(languages) > limit else ""
    return f"Versions present: {', '.join(versions)}. Monolingual languages: {shown}{suffix}."


def _archive_name(record: OpusFileRecord) -> str:
    """Local name of the archive, as `opustools` derives it from the URL.

    The instance is built with the record's *concrete* version: with ``release='latest'``,
    `make_file_name` would replace the version with ``latest`` in the name, and the archive
    would lose track of which release it contains.
    """
    getter = _opus_getter(version=record.version)
    fields: Mapping[str, str] = {"url": record.url, "version": record.version}
    return Path(getter.make_file_name(fields)).name


def _total_size(response: httpx.Response, resume_from: int) -> int | None:
    """Final size of the archive, derived from the headers.

    On a resume, ``Content-Length`` only describes the remainder: ``Content-Range`` is the
    one carrying the total. Without it, we add the offset already acquired.
    """
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        declared = content_range.rsplit("/", 1)[1]
        if declared.isdigit():
            return int(declared)

    length = response.headers.get("Content-Length", "")
    if length.isdigit():
        return resume_from + int(length)
    return None


def _stream_to_file(
    url: str,
    *,
    archive_path: Path,
    force: bool,
    progress: ProgressCallback | None,
    client: httpx.Client | None,
) -> Sha256 | None:
    """Downloads `url` to `archive_path`, resuming an existing ``.part`` if present.

    Returns:
        The archive's checksum when the transfer started from zero — the computation is
        then free, done on the fly. `None` after a resume: the bytes already present never
        went through hashing, and a full pass over dozens of gigabytes doesn't get decided
        on its own.

    Raises:
        CorpusError: transfer interrupted or write impossible.
    """
    part = archive_path.with_name(archive_path.name + _PART_SUFFIX)
    resume_from = part.stat().st_size if part.is_file() and not force else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    if resume_from:
        _log.info("resuming download at %d bytes: %s", resume_from, part.name)

    owned = client is None
    http = client if client is not None else _make_client()
    digest = hashlib.sha256()
    hashed = True

    try:
        with http.stream("GET", url, headers=headers) as response:
            if resume_from and response.status_code == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
                _log.warning(
                    "server considers the ``.part`` complete (416): %s is renamed as-is,"
                    " archive verification will settle it",
                    part.name,
                )
                part.replace(archive_path)
                return None

            if resume_from and response.status_code != httpx.codes.PARTIAL_CONTENT:
                _log.warning("server ignores the Range header: download resumed from zero")
                resume_from = 0

            response.raise_for_status()
            total = _total_size(response, resume_from)
            received = resume_from
            hashed = resume_from == 0
            if progress is not None:
                progress(received, total)

            with part.open("ab" if resume_from else "wb") as handle:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    handle.write(chunk)
                    if hashed:
                        digest.update(chunk)
                    received += len(chunk)
                    if progress is not None:
                        progress(received, total)
    except httpx.HTTPError as exc:
        message = (
            f"download interrupted ({url}): {exc}. The file {part.name} is kept,"
            " a new call will resume where it stopped."
        )
        raise CorpusError(message) from exc
    except OSError as exc:
        message = f"cannot write to {part}: {exc}"
        raise CorpusError(message) from exc
    finally:
        if owned:
            http.close()

    # Renaming last: until it happens, an incomplete archive cannot be mistaken for a
    # complete one.
    part.replace(archive_path)
    return digest.hexdigest() if hashed else None


def download_corpus(
    *,
    dest_dir: Path,
    corpus: str = DEFAULT_CORPUS,
    version: OpusVersion = DEFAULT_VERSION,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    force: bool = False,
    record: OpusFileRecord | None = None,
    progress: ProgressCallback | None = None,
    client: httpx.Client | None = None,
) -> CorpusDownload:
    """Downloads the monolingual archive of an OPUS corpus.

    The archive is stored as-is: it is not decompressed, it *is* the corpus.

    Args:
        dest_dir: directory where the archive is stored.
        corpus: name of the OPUS corpus.
        version: targeted release.
        language: language code.
        preprocessing: preprocessing variant.
        force: re-downloads even if the archive is already present.
        record: already resolved record, to avoid a second call to the index.
        progress: progress callback.
        client: HTTP client to reuse.

    Returns:
        The description of the archive obtained.

    Raises:
        MetadataError: the OPUS index is unreachable.
        CorpusError: download impossible or archive incomplete.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    if record is None:
        record = resolve_archive(
            corpus=corpus,
            version=version,
            language=language,
            preprocessing=preprocessing,
            client=client,
        )

    archive_path = dest_dir / _archive_name(record)
    announced = record.size * _KIB
    # `debug` and not `info`: the CLI already announces the chosen URL before starting the
    # transfer, and repeating it in the log would only duplicate the same line.
    _log.debug("OPUS archive: %s (%d bytes announced)", record.url, announced)

    if archive_path.is_file() and not force:
        _warn_on_size_mismatch(archive_path, announced=announced)
        _log.info("archive already present, download skipped: %s", archive_path)
        sha256 = None
    else:
        sha256 = _stream_to_file(
            record.url,
            archive_path=archive_path,
            force=force,
            progress=progress,
            client=client,
        )

    return CorpusDownload(
        corpus=record.corpus,
        version=record.version,
        language=record.source,
        archive_path=archive_path,
        sha256=sha256,
        url=record.url,
    )


def _warn_on_size_mismatch(archive_path: Path, *, announced: int) -> None:
    """Flags an archive whose size deviates from what the index announces."""
    if not announced:
        return
    actual = archive_path.stat().st_size
    if abs(actual - announced) > announced * _SIZE_TOLERANCE:
        _log.warning(
            "%s is %d bytes, the index announces ~%d: archive probably incomplete."
            " Rerun with --force.",
            archive_path.name,
            actual,
            announced,
        )
