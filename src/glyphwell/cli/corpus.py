"""Subcommands ``glyphwell corpus``.

STATUS: ``fetch`` and ``index`` are operational; ``refresh`` remains pending.
"""

import hashlib
import sqlite3
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Annotated, Final

import typer
from rich.filesize import decimal
from rich.progress import (
    BarColumn,
    DownloadColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from glyphwell.cli.context import get_context
from glyphwell.config import Settings
from glyphwell.console import console
from glyphwell.corpus.archive import ArchiveSummary, CorpusArchive
from glyphwell.corpus.hashing import DEFAULT_CHUNK_SIZE, sha256_file
from glyphwell.corpus.layout import CorpusEntry, iter_corpus
from glyphwell.corpus.opus import (
    DEFAULT_CORPUS,
    DEFAULT_VERSION,
    CorpusDownload,
    OpusFileRecord,
    download_corpus,
    resolve_archive,
)
from glyphwell.db import connect, ensure_current
from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
    SubtitleFileRow,
    SubtitleFilesRepository,
)
from glyphwell.errors import CorpusError, DatabaseError, GlyphwellError
from glyphwell.logging import get_logger
from glyphwell.types import Sha256

__all__ = ["app"]

app = typer.Typer(
    help="Download, indexing and refreshing of the subtitle corpus.",
    no_args_is_help=True,
)

_log = get_logger(__name__)

_CATALOG_BATCH_SIZE: Final = 2_000
"""Files per cataloging/hashing transaction — bigger batches, fewer WAL commits."""


@app.command("fetch")
def fetch(
    ctx: typer.Context,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="OPUS language code. Default: the one from .env"),
    ] = None,
    version: Annotated[
        str,
        typer.Option("--version", help="Target OPUS release."),
    ] = DEFAULT_VERSION,
    corpus_name: Annotated[
        str,
        typer.Option("--corpus", help="Name of the OPUS corpus."),
    ] = DEFAULT_CORPUS,
    dest: Annotated[
        Path | None,
        typer.Option(
            "--dest", help="Directory to store the archive in. Default: <data-dir>/corpus"
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-downloads even if the archive is already present."),
    ] = False,
    compute_hash: Annotated[
        bool,
        typer.Option("--hash", help="Computes the checksum even if no transfer took place."),
    ] = False,
) -> None:
    """Downloads the corpus (`raw` format, a single language).

    The archive is **not** decompressed: it is the corpus, and subtitles are read from
    it on the fly. Expect several tens of GB for the full English corpus. An
    interrupted download resumes where it left off.
    """
    settings = get_context(ctx).settings
    settings.ensure_directories()
    target_language = language or settings.opus_language
    dest_dir = dest if dest is not None else settings.corpus_dir

    record = resolve_archive(corpus=corpus_name, version=version, language=target_language)
    _announce(record, dest_dir=dest_dir)

    download_id = _upsert_pending(settings, record)
    try:
        result = _download(record, dest_dir=dest_dir, force=force)
        summary = _verify(result.archive_path)
        sha256 = _resolve_hash(result, compute_hash=compute_hash)
    except GlyphwellError:
        _mark(settings, download_id, DownloadStatus.FAILED)
        raise

    _mark(
        settings,
        download_id,
        DownloadStatus.DOWNLOADED,
        sha256=sha256,
        archive_path=str(result.archive_path),
        verified=True,
    )
    _report(result, summary=summary, sha256=sha256)


def _announce(record: OpusFileRecord, *, dest_dir: Path) -> None:
    """Displays what the user is committing to, before any transfer."""
    console.print(f"OPUS archive: [bold]{record.url}[/bold]")
    console.print(
        f"Release [bold]{record.version}[/bold], language [bold]{record.source}[/bold],"
        f" preprocessing [bold]{record.preprocessing}[/bold] —"
        f" about {decimal(record.size * 1024)}"
    )
    console.print(f"Destination: {dest_dir}")


def _download(record: OpusFileRecord, *, dest_dir: Path, force: bool) -> CorpusDownload:
    """Downloads the archive, showing volume, throughput and remaining time.

    The live display only starts on the first actual progress callback: when the
    archive is already present, `download_corpus` never calls it, and no bar should
    appear for a transfer that never happens.
    """
    progress = Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    )
    task: TaskID | None = None

    def on_progress(received: int, total: int | None) -> None:
        nonlocal task
        if task is None:
            progress.start()
            # `total=None` until the headers have been read: the bar stays
            # indeterminate rather than showing a made-up percentage.
            task = progress.add_task("downloading", total=None)
        progress.update(task, completed=received, total=total)

    try:
        return download_corpus(
            dest_dir=dest_dir,
            corpus=record.corpus,
            version=record.version,
            language=record.source,
            force=force,
            record=record,
            progress=on_progress,
        )
    finally:
        if task is not None:
            progress.stop()


def _verify(archive_path: Path) -> ArchiveSummary:
    """Opens the archive and describes its content, without extracting anything."""
    with CorpusArchive(archive_path) as archive:
        return archive.summarize()


def _resolve_hash(result: CorpusDownload, *, compute_hash: bool) -> Sha256 | None:
    """Archive checksum, computed on the fly or on explicit request.

    A full pass over several tens of GB takes several minutes: it does not trigger
    on its own when the transfer could not produce it for free.
    """
    if result.sha256 is not None or not compute_hash:
        return result.sha256

    console.print("Computing checksum…")
    return sha256_file(result.archive_path)


def _report(result: CorpusDownload, *, summary: ArchiveSummary, sha256: Sha256 | None) -> None:
    """Summarizes the acquisition."""
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Archive", str(result.archive_path))
    table.add_row("Size", decimal(result.archive_path.stat().st_size))
    table.add_row("Checksum", sha256 or "not computed (use --hash to force it)")
    table.add_row("Subtitles", f"{summary.subtitle_count:,}".replace(",", " "))
    if summary.metadata_count:
        # OPUS archives embed INFO / README / LICENSE: mentioned once, without alarm.
        table.add_row("Service files", str(summary.metadata_count))
    console.print(table)

    if summary.samples:
        console.print("Internal layout:")
        for sample in summary.samples:
            console.print(f"  {sample}")

    if summary.unexpected_count:
        console.print(
            f"[yellow]Warning[/yellow]: {summary.unexpected_count} member(s) have an"
            f" unexpected extension, for example {summary.unexpected_samples[0]}."
            " These might be subtitles that glyphwell cannot read — worth checking"
            " before going further."
        )


def _upsert_pending(settings: Settings, record: OpusFileRecord) -> int:
    """Records the acquisition as `pending` before starting the transfer.

    Deliberately written *before* the download: a missing database must fail the
    command right away, not after several tens of GB.
    """
    with connect(settings.database_path) as conn:
        ensure_current(conn)
        return CorpusDownloadsRepository(conn).upsert(
            CorpusDownloadRow(
                opus_corpus=record.corpus,
                opus_version=record.version,
                language=record.source,
                url=record.url,
                archive_path=None,
                sha256=None,
                status=DownloadStatus.PENDING,
            )
        )


def _mark(
    settings: Settings,
    download_id: int,
    status: DownloadStatus,
    *,
    sha256: Sha256 | None = None,
    archive_path: str | None = None,
    verified: bool = False,
) -> None:
    """Advances the traceability row."""
    with connect(settings.database_path) as conn:
        CorpusDownloadsRepository(conn).mark(
            download_id,
            status,
            sha256=sha256,
            archive_path=archive_path,
            verified=verified,
        )


@app.command("index")
def index(
    ctx: typer.Context,
    rehash: Annotated[
        bool,
        typer.Option("--rehash", help="Recomputes the checksum of files already cataloged."),
    ] = False,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Restricts the scan to a single language."),
    ] = None,
) -> None:
    """Scans the archive and populates the `subtitle_files` table.

    Does not read subtitle content: only the member name, its size and its checksum
    are recorded. IMDb identifiers come from the internal layout.
    """
    settings = get_context(ctx).settings
    target_language = language or settings.opus_language

    with connect(settings.database_path) as conn:
        ensure_current(conn)
        download = CorpusDownloadsRepository(conn).get(
            opus_corpus=settings.opus_corpus,
            opus_version=settings.opus_version,
            language=target_language,
        )
        archive_path = _require_downloaded_archive(download, target_language)

        with CorpusArchive(archive_path) as archive:
            summary = archive.summarize()
            _announce_index(archive_path, summary, rehash=rehash)

            cataloged = _catalog(
                conn,
                archive,
                opus_version=settings.opus_version,
                language=target_language,
                total=summary.subtitle_count,
            )
            repo = SubtitleFilesRepository(conn)
            if rehash:
                hashed, skipped = _hash_files(
                    conn,
                    repo,
                    archive,
                    _iter_cataloged(
                        repo, archive, opus_version=settings.opus_version, language=target_language
                    ),
                    total=summary.subtitle_count,
                    description="rehashing",
                )
            else:
                hashed, skipped = _hash_files(
                    conn, repo, archive, repo.iter_stale(), total=None, description="hashing"
                )

    _report_index(summary=summary, cataloged=cataloged, hashed=hashed, skipped=skipped)


def _require_downloaded_archive(download: CorpusDownloadRow | None, language: str) -> Path:
    """Locates the already-downloaded archive for a language, offline.

    Deliberately does not re-resolve against the live OPUS index: the whole point of
    `corpus_downloads` traceability is to answer "where is the archive" without a second
    network round trip.
    """
    if download is None or download.status is not DownloadStatus.DOWNLOADED:
        message = (
            f"no downloaded archive for language {language!r}. Run `glyphwell corpus fetch` first."
        )
        raise CorpusError(message)
    if download.archive_path is None:
        message = (
            f"corpus_downloads has no archive_path for language {language!r} — inconsistent state."
        )
        raise CorpusError(message)
    return Path(download.archive_path)


def _announce_index(archive_path: Path, summary: ArchiveSummary, *, rehash: bool) -> None:
    """Displays what is about to be scanned, before any write."""
    console.print(f"Archive: [bold]{archive_path}[/bold]")
    console.print(f"Subtitles found: {summary.subtitle_count:,}".replace(",", " "))
    if rehash:
        console.print("Recomputing checksums for every already-cataloged file (--rehash).")


def _progress_bar() -> Progress:
    """A progress bar for a file-count-based operation (not a byte transfer)."""
    return Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeRemainingColumn(),
        console=console,
    )


def _catalog(
    conn: sqlite3.Connection,
    archive: CorpusArchive,
    *,
    opus_version: str,
    language: str,
    total: int,
) -> int:
    """Walks the archive and upserts every entry into `subtitle_files`.

    Never reads subtitle content: only what `iter_corpus` derives from the member name.
    """
    repo = SubtitleFilesRepository(conn)
    count = 0
    with _progress_bar() as progress:
        task = progress.add_task("cataloging", total=total)
        batch: list[CorpusEntry] = []
        for entry in iter_corpus(archive, language=language):
            batch.append(entry)
            if len(batch) >= _CATALOG_BATCH_SIZE:
                count += _flush_catalog(conn, repo, opus_version, batch)
                progress.advance(task, len(batch))
                batch.clear()
        if batch:
            count += _flush_catalog(conn, repo, opus_version, batch)
            progress.advance(task, len(batch))
    return count


def _flush_catalog(
    conn: sqlite3.Connection,
    repo: SubtitleFilesRepository,
    opus_version: str,
    batch: list[CorpusEntry],
) -> int:
    """Upserts one batch of entries in a single transaction.

    `isolation_level=None` (see `db.connection`) disables sqlite3's implicit autocommit:
    nothing is transactional here unless stated explicitly.
    """
    conn.execute("BEGIN")
    try:
        for entry in batch:
            repo.upsert(
                SubtitleFileRow(
                    file_id=0,  # disregarded by `upsert`, matched on the natural key
                    opus_version=opus_version,
                    language=entry.language,
                    imdb_id=entry.imdb_id,
                    opensubtitles_file_id=entry.opensubtitles_file_id,
                    rel_path=entry.rel_path,
                    year=entry.year,
                    sha256=None,
                    size_bytes=None,
                    sentence_count=None,
                )
            )
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        message = f"cataloging failed: {exc}"
        raise DatabaseError(message) from exc
    conn.execute("COMMIT")
    return len(batch)


def _iter_cataloged(
    repo: SubtitleFilesRepository,
    archive: CorpusArchive,
    *,
    opus_version: str,
    language: str,
) -> Iterator[SubtitleFileRow]:
    """Re-walks the archive and looks up each entry's already-cataloged row.

    Cheap: only the central directory is read again, no decompression. Used by
    ``--rehash`` to revisit every entry regardless of whether it already has a checksum.
    """
    for entry in iter_corpus(archive, language=language):
        found = repo.get_by_path(
            opus_version=opus_version, language=entry.language, rel_path=entry.rel_path
        )
        if found is not None:
            yield found


def _hash_member(archive: CorpusArchive, rel_path: str) -> tuple[Sha256, int]:
    """Computes a member's checksum and byte size in a single pass over its stream."""
    digest = hashlib.sha256()
    size = 0
    with archive.open_member(rel_path) as stream:
        while chunk := stream.read(DEFAULT_CHUNK_SIZE):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _hash_files(
    conn: sqlite3.Connection,
    repo: SubtitleFilesRepository,
    archive: CorpusArchive,
    rows: Iterable[SubtitleFileRow],
    *,
    total: int | None,
    description: str,
) -> tuple[int, int]:
    """Hashes a stream of already-cataloged rows, batching the writes.

    Returns ``(hashed, skipped)``. An individual unreadable member is logged and skipped
    rather than aborting a scan that can span hundreds of thousands of files.
    """
    hashed = 0
    skipped = 0
    with _progress_bar() as progress:
        task = progress.add_task(description, total=total)
        batch: list[SubtitleFileRow] = []
        for row in rows:
            batch.append(row)
            if len(batch) >= _CATALOG_BATCH_SIZE:
                batch_hashed, batch_skipped = _hash_batch(conn, repo, archive, batch)
                hashed += batch_hashed
                skipped += batch_skipped
                progress.advance(task, len(batch))
                batch.clear()
        if batch:
            batch_hashed, batch_skipped = _hash_batch(conn, repo, archive, batch)
            hashed += batch_hashed
            skipped += batch_skipped
            progress.advance(task, len(batch))
    return hashed, skipped


def _hash_batch(
    conn: sqlite3.Connection,
    repo: SubtitleFilesRepository,
    archive: CorpusArchive,
    rows: list[SubtitleFileRow],
) -> tuple[int, int]:
    """Hashes and writes one batch in a single transaction."""
    hashed = 0
    skipped = 0
    conn.execute("BEGIN")
    try:
        for row in rows:
            try:
                sha256, size = _hash_member(archive, row.rel_path)
            except CorpusError as exc:
                skipped += 1
                _log.warning("could not hash %s: %s", row.rel_path, exc)
                continue
            repo.set_hash(row.file_id, sha256, size_bytes=size)
            hashed += 1
    except sqlite3.Error as exc:
        conn.execute("ROLLBACK")
        message = f"indexing failed while writing checksums: {exc}"
        raise DatabaseError(message) from exc
    conn.execute("COMMIT")
    return hashed, skipped


def _report_index(
    *,
    summary: ArchiveSummary,
    cataloged: int,
    hashed: int,
    skipped: int,
) -> None:
    """Summarizes the indexing pass."""
    table = Table(show_header=False, box=None)
    table.add_column("Field", style="bold")
    table.add_column("Value")
    table.add_row("Subtitles in archive", f"{summary.subtitle_count:,}".replace(",", " "))
    table.add_row("Cataloged", f"{cataloged:,}".replace(",", " "))
    table.add_row("Checksums computed", f"{hashed:,}".replace(",", " "))
    if skipped:
        table.add_row("Skipped (unreadable)", str(skipped))
    console.print(table)

    if summary.unexpected_count:
        console.print(
            f"[yellow]Warning[/yellow]: {summary.unexpected_count} member(s) have an"
            f" unexpected extension, for example {summary.unexpected_samples[0]}."
        )


@app.command("refresh")
def refresh(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Lists what would be invalidated, without writing anything."
        ),
    ] = False,
) -> None:
    """Detects modified subtitles and invalidates their results.

    Recomputes the checksum of each cataloged file. If it differs, only that file's
    results are deleted and its cursor reset in each search: the rest of the
    searches are kept.
    """
    settings = get_context(ctx).settings
    _ = (settings, dry_run)
    raise NotImplementedError
