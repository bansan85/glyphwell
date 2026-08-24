"""Sous-commandes ``glyphwell corpus``.

STATUT : ``fetch`` est opérationnelle ; ``index`` et ``refresh`` restent en attente.
"""

from pathlib import Path
from typing import Annotated

import typer
from rich.filesize import decimal
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)
from rich.table import Table

from glyphwell.cli.context import get_context
from glyphwell.config import Settings
from glyphwell.console import console
from glyphwell.corpus.archive import ArchiveSummary, CorpusArchive
from glyphwell.corpus.hashing import sha256_file
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
)
from glyphwell.errors import GlyphwellError
from glyphwell.logging import get_logger
from glyphwell.types import Sha256

__all__ = ["app"]

app = typer.Typer(
    help="Téléchargement, indexation et rafraîchissement du corpus de sous-titres.",
    no_args_is_help=True,
)

_log = get_logger(__name__)


@app.command("fetch")
def fetch(
    ctx: typer.Context,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Code de langue OPUS. Défaut : celui du .env"),
    ] = None,
    version: Annotated[
        str,
        typer.Option("--version", help="Release OPUS visée."),
    ] = DEFAULT_VERSION,
    corpus_name: Annotated[
        str,
        typer.Option("--corpus", help="Nom du corpus OPUS."),
    ] = DEFAULT_CORPUS,
    dest: Annotated[
        Path | None,
        typer.Option("--dest", help="Répertoire où déposer l'archive. Défaut : <data-dir>/corpus"),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Re-télécharge même si l'archive est déjà présente."),
    ] = False,
    compute_hash: Annotated[
        bool,
        typer.Option("--hash", help="Calcule l'empreinte même si le transfert n'a pas eu lieu."),
    ] = False,
) -> None:
    """Télécharge le corpus (format `raw`, une seule langue).

    L'archive n'est **pas** décompressée : elle est le corpus, et les sous-titres en sont
    lus à la volée. Prévoir plusieurs dizaines de Go pour l'anglais complet. Un
    téléchargement interrompu reprend là où il s'était arrêté.
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
    """Affiche ce sur quoi l'utilisateur s'engage, avant tout transfert."""
    console.print(f"Archive OPUS : [bold]{record.url}[/bold]")
    console.print(
        f"Release [bold]{record.version}[/bold], langue [bold]{record.source}[/bold],"
        f" préprocessing [bold]{record.preprocessing}[/bold] —"
        f" environ {decimal(record.size * 1024)}"
    )
    console.print(f"Destination : {dest_dir}")


def _download(record: OpusFileRecord, *, dest_dir: Path, force: bool) -> CorpusDownload:
    """Télécharge l'archive en affichant volume, débit et temps restant."""
    with Progress(
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        # `total=None` tant que les en-têtes n'ont pas été lus : la barre reste
        # indéterminée plutôt que d'afficher un pourcentage inventé.
        task = progress.add_task("téléchargement", total=None)

        def on_progress(received: int, total: int | None) -> None:
            progress.update(task, completed=received, total=total)

        return download_corpus(
            dest_dir=dest_dir,
            corpus=record.corpus,
            version=record.version,
            language=record.source,
            force=force,
            record=record,
            progress=on_progress,
        )


def _verify(archive_path: Path) -> ArchiveSummary:
    """Ouvre l'archive et décrit son contenu, sans rien extraire."""
    with CorpusArchive(archive_path) as archive:
        return archive.summarize()


def _resolve_hash(result: CorpusDownload, *, compute_hash: bool) -> Sha256 | None:
    """Empreinte de l'archive, calculée au vol ou sur demande explicite.

    Une passe complète sur plusieurs dizaines de Go dure plusieurs minutes : elle ne se
    déclenche pas d'elle-même quand le transfert n'a pas pu la produire gratuitement.
    """
    if result.sha256 is not None or not compute_hash:
        return result.sha256

    console.print("Calcul de l'empreinte…")
    return sha256_file(result.archive_path)


def _report(result: CorpusDownload, *, summary: ArchiveSummary, sha256: Sha256 | None) -> None:
    """Récapitule l'acquisition."""
    table = Table(show_header=False, box=None)
    table.add_column("Champ", style="bold")
    table.add_column("Valeur")
    table.add_row("Archive", str(result.archive_path))
    table.add_row("Taille", decimal(result.archive_path.stat().st_size))
    table.add_row("Empreinte", sha256 or "non calculée (--hash pour la forcer)")
    table.add_row("Sous-titres", f"{summary.subtitle_count:,}".replace(",", " "))
    if summary.metadata_count:
        # Les archives OPUS embarquent INFO / README / LICENSE : dit une fois, sans alarme.
        table.add_row("Fichiers de service", str(summary.metadata_count))
    console.print(table)

    if summary.samples:
        console.print("Arborescence interne :")
        for sample in summary.samples:
            console.print(f"  {sample}")

    if summary.unexpected_count:
        console.print(
            f"[yellow]Attention[/yellow] : {summary.unexpected_count} membre(s) portent une"
            f" extension inattendue, par exemple {summary.unexpected_samples[0]}."
            " Ce sont peut-être des sous-titres que glyphwell ne sait pas lire — à vérifier"
            " avant d'aller plus loin."
        )


def _upsert_pending(settings: Settings, record: OpusFileRecord) -> int:
    """Enregistre l'acquisition en `pending` avant d'engager le transfert.

    Écrit délibérément *avant* le téléchargement : une base absente doit faire échouer la
    commande tout de suite, pas après plusieurs dizaines de Go.
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
    """Fait avancer la ligne de traçabilité."""
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
        typer.Option("--rehash", help="Recalcule l'empreinte des fichiers déjà catalogués."),
    ] = False,
    language: Annotated[
        str | None,
        typer.Option("--language", "-l", help="Restreint le scan à une langue."),
    ] = None,
) -> None:
    """Parcourt l'archive et alimente la table `subtitle_files`.

    Ne lit pas le contenu des sous-titres : seuls le nom du membre, sa taille et son
    empreinte sont relevés. Les identifiants IMDb proviennent de l'arborescence interne.
    """
    settings = get_context(ctx).settings
    _ = (settings, rehash, language)
    raise NotImplementedError


@app.command("refresh")
def refresh(
    ctx: typer.Context,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Liste ce qui serait invalidé, sans rien écrire."),
    ] = False,
) -> None:
    """Détecte les sous-titres modifiés et invalide leurs résultats.

    Recalcule l'empreinte de chaque fichier catalogué. Si elle diffère, seuls les résultats
    de ce fichier sont supprimés et son curseur remis à zéro dans chaque recherche : le reste
    des recherches est conservé.
    """
    settings = get_context(ctx).settings
    _ = (settings, dry_run)
    raise NotImplementedError
