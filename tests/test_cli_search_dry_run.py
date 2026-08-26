"""`glyphwell search run --dry-run`: a fully rendered example prompt, no side effects."""

import zipfile
from pathlib import Path

from typer.testing import CliRunner

from glyphwell.cli import app
from glyphwell.config import Settings
from glyphwell.db import connect, initialize_catalog
from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
    TitleRow,
    TitlesRepository,
)

runner = CliRunner()


def _build_archive(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "OpenSubtitles/raw/en/1999/0133093/1.xml",
            '<document><s id="1">We should hit the ski slopes tomorrow.</s>'
            '<s id="2">Sounds perfect.</s></document>',
        )


def _seed(settings: Settings, archive_path: Path) -> None:
    with connect(settings.catalog_database_path, create=True) as conn:
        initialize_catalog(conn)
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
        TitlesRepository(conn).upsert_many(
            [
                TitleRow(
                    imdb_id="tt0133093",
                    title_type="movie",
                    primary_title="Ski Trip",
                    original_title=None,
                    start_year=1999,
                    end_year=None,
                    parent_imdb_id=None,
                    season_number=None,
                    episode_number=None,
                )
            ]
        )


def test_dry_run_renders_a_real_chunk_without_touching_the_database(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, _env_file=None)
    archive_path = tmp_path / "corpus.zip"
    _build_archive(archive_path)
    _seed(settings, archive_path)

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "name: dry_run_test\n"
        "model: test-model\n"
        "chunk:\n"
        "  size: 2\n"
        "  overlap: 0\n"
        "prompt:\n"
        "  user: |\n"
        "    {{ chunk }}\n"
        "output:\n"
        "  format: text\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["--data-dir", str(data_dir), "search", "run", str(manifest_path), "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "ski slopes" in result.output
    assert "{{ chunk }}" not in result.output
    assert "test-model" in result.output
    assert "Ski Trip" in result.output

    # `--dry-run` never creates a run database: the default one (derived from the
    # manifest's filename) must not exist.
    assert not (data_dir / "manifest.db").exists()


def test_dry_run_without_a_match_fails_cleanly(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    settings = Settings(data_dir=data_dir, _env_file=None)
    archive_path = tmp_path / "corpus.zip"
    _build_archive(archive_path)
    _seed(settings, archive_path)

    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        "name: no_match\n"
        "model: test-model\n"
        "select:\n"
        "  languages: [fr]\n"
        "prompt:\n"
        "  user: |\n"
        "    {{ chunk }}\n",
        encoding="utf-8",
    )

    result = runner.invoke(
        app, ["--data-dir", str(data_dir), "search", "run", str(manifest_path), "--dry-run"]
    )

    assert result.exit_code != 0
    # `CliRunner.invoke(app, ...)` calls the Typer app directly, bypassing `main()`'s
    # pretty-printing of `GlyphwellError` — the raised exception itself is what's
    # actionable here, not `result.output`.
    assert result.exception is not None
    assert "match" in str(result.exception).lower()
