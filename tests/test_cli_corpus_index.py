"""`glyphwell corpus index` populates `subtitle_files` from a downloaded archive."""

import zipfile
from pathlib import Path

from typer.testing import CliRunner

from glyphwell.cli import app
from glyphwell.config import Settings
from glyphwell.db import connect
from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
    SubtitleFilesRepository,
)

runner = CliRunner()


def _build_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "OpenSubtitles/raw/en/1999/0133093/1.xml", '<document><s id="1">Hello.</s></document>'
        )
        archive.writestr(
            "OpenSubtitles/raw/en/2001/0234215/2.xml", '<document><s id="1">World.</s></document>'
        )


def _seed_download(settings: Settings, archive_path: Path) -> None:
    with connect(settings.database_path) as conn:
        CorpusDownloadsRepository(conn).upsert(
            CorpusDownloadRow(
                opus_corpus=settings.opus_corpus,
                opus_version=settings.opus_version,
                language=settings.opus_language,
                url=None,
                archive_path=str(archive_path),
                sha256=None,
                status=DownloadStatus.DOWNLOADED,
            )
        )


def test_index_without_a_prior_fetch_fails_cleanly(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    init = runner.invoke(app, ["--data-dir", str(data_dir), "db", "init"])
    assert init.exit_code == 0, init.output

    result = runner.invoke(app, ["--data-dir", str(data_dir), "corpus", "index"])
    assert result.exit_code != 0
    # `CliRunner.invoke(app, ...)` calls the Typer app directly, bypassing `main()`'s
    # pretty-printing of `GlyphwellError` — the raised exception itself is what's
    # actionable here, not `result.output`.
    assert result.exception is not None
    assert "fetch" in str(result.exception)


def test_index_catalogs_every_subtitle(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, _env_file=None)
    archive_path = tmp_path / "corpus.zip"
    _build_archive(archive_path)

    init = runner.invoke(app, ["--data-dir", str(data_dir), "db", "init"])
    assert init.exit_code == 0, init.output
    _seed_download(settings, archive_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "corpus", "index"])
    assert result.exit_code == 0, result.output

    with connect(settings.database_path) as conn:
        repo = SubtitleFilesRepository(conn)
        assert repo.count() == 2
        row = repo.get_by_path(
            opus_version=settings.opus_version,
            language=settings.opus_language,
            rel_path="OpenSubtitles/raw/en/1999/0133093/1.xml",
        )
        assert row is not None
        assert row.imdb_id == "tt0133093"
        assert row.year == 1999


def test_index_catalogs_archive_with_skipped_members(tmp_path: Path) -> None:
    """Members outside the target language or the expected layout must still be
    counted towards `Subtitles in archive`, not just the ones actually cataloged —
    they were previously invisible to the progress bar's total (see `iter_corpus`'s
    `on_member` callback).
    """
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, _env_file=None)
    archive_path = tmp_path / "corpus.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "OpenSubtitles/raw/en/1999/0133093/1.xml", '<document><s id="1">Hello.</s></document>'
        )
        archive.writestr(
            "OpenSubtitles/raw/fr/2001/0234215/2.xml", '<document><s id="1">Bonjour.</s></document>'
        )
        archive.writestr("bad/shape.xml", "<document/>")

    init = runner.invoke(app, ["--data-dir", str(data_dir), "db", "init"])
    assert init.exit_code == 0, init.output
    _seed_download(settings, archive_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "corpus", "index"])
    assert result.exit_code == 0, result.output

    with connect(settings.database_path) as conn:
        assert SubtitleFilesRepository(conn).count() == 1


def test_index_is_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, _env_file=None)
    archive_path = tmp_path / "corpus.zip"
    _build_archive(archive_path)

    runner.invoke(app, ["--data-dir", str(data_dir), "db", "init"])
    _seed_download(settings, archive_path)
    runner.invoke(app, ["--data-dir", str(data_dir), "corpus", "index"])
    second = runner.invoke(app, ["--data-dir", str(data_dir), "corpus", "index"])
    assert second.exit_code == 0, second.output

    with connect(settings.database_path) as conn:
        assert SubtitleFilesRepository(conn).count() == 2
