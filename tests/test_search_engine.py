"""End-to-end search engine behavior, driven by a fake `LlmClient` (no real Ollama)."""

import sqlite3
import zipfile
from collections.abc import Mapping
from pathlib import Path
from typing import override

import pytest

from glyphwell.config import Settings
from glyphwell.db import connect, initialize_catalog, initialize_run
from glyphwell.db.repositories import (
    CorpusDownloadRow,
    CorpusDownloadsRepository,
    DownloadStatus,
    RunsRepository,
    RunStatus,
    SubtitleFileRow,
    SubtitleFilesRepository,
    TitleRow,
    TitlesRepository,
)
from glyphwell.errors import OllamaError
from glyphwell.manifest import load
from glyphwell.ollama.client import Completion
from glyphwell.search import planner
from glyphwell.search.engine import SearchEngine
from glyphwell.types import JsonValue


class _FakeLlmClient:
    """Deterministic `LlmClient`: never touches a real Ollama server."""

    def __init__(self) -> None:
        self.calls = 0

    def ensure_model(self, model: str) -> None:
        return None

    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: Mapping[str, JsonValue] | None = None,
        json_schema: Mapping[str, JsonValue] | None = None,
    ) -> Completion:
        self.calls += 1
        return Completion(text="ok", payload=None, model=model, latency_ms=1)


class _StoppingLlmClient(_FakeLlmClient):
    """Requests a stop as soon as the first chunk's completion is produced."""

    def __init__(self) -> None:
        super().__init__()
        self.engine: SearchEngine | None = None

    @override
    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: Mapping[str, JsonValue] | None = None,
        json_schema: Mapping[str, JsonValue] | None = None,
    ) -> Completion:
        completion = super().complete(
            model=model, user=user, system=system, options=options, json_schema=json_schema
        )
        assert self.engine is not None
        self.engine.request_stop()
        return completion


class _FailingLlmClient(_FakeLlmClient):
    """Fails every call: exercises per-file error isolation."""

    @override
    def complete(
        self,
        *,
        model: str,
        user: str,
        system: str | None = None,
        options: Mapping[str, JsonValue] | None = None,
        json_schema: Mapping[str, JsonValue] | None = None,
    ) -> Completion:
        self.calls += 1
        message = "the model exploded"
        raise OllamaError(message)


def _write_manifest(tmp_path: Path, *, name: str = "t") -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text(
        f"name: {name}\n"
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
    return path


def _build_archive(tmp_path: Path) -> Path:
    path = tmp_path / "corpus.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "OpenSubtitles/raw/en/1999/0133093/1.xml",
            '<document><s id="1">Hello.</s><s id="2">World.</s>'
            '<s id="3">Foo.</s><s id="4">Bar.</s></document>',
        )
    return path


def _seed(settings: Settings, catalog_conn: sqlite3.Connection, archive_path: Path) -> None:
    CorpusDownloadsRepository(catalog_conn).upsert(
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
    TitlesRepository(catalog_conn).upsert_many(
        [
            TitleRow(
                imdb_id="tt0133093",
                title_type="movie",
                primary_title="Test Movie",
                original_title=None,
                start_year=1999,
                end_year=None,
                parent_imdb_id=None,
                season_number=None,
                episode_number=None,
            )
        ]
    )
    SubtitleFilesRepository(catalog_conn).upsert(
        SubtitleFileRow(
            file_id=0,
            opus_version=settings.opus_version,
            language=settings.opus_language,
            imdb_id="tt0133093",
            opensubtitles_file_id="1",
            rel_path="OpenSubtitles/raw/en/1999/0133093/1.xml",
            year=1999,
            size_bytes=None,
            sentence_count=None,
        )
    )


def test_start_processes_every_chunk_of_every_file(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.ensure_directories()
    archive_path = _build_archive(tmp_path)

    with (
        connect(settings.catalog_database_path, create=True) as catalog_conn,
        connect(tmp_path / "data" / "run.db", create=True) as run_conn,
    ):
        initialize_catalog(catalog_conn)
        initialize_run(run_conn)
        _seed(settings, catalog_conn, archive_path)
        client = _FakeLlmClient()
        engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=client, settings=settings
        )
        outcome = engine.start(load(_write_manifest(tmp_path)))

    assert outcome.files_done == 1
    assert outcome.chunks_done == 2
    assert outcome.chunks_skipped == 0
    assert outcome.matches == 2
    assert outcome.interrupted is False
    assert client.calls == 2


def test_start_creates_a_new_run_when_the_previous_one_is_done(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.ensure_directories()
    archive_path = _build_archive(tmp_path)
    manifest_path = _write_manifest(tmp_path)

    with (
        connect(settings.catalog_database_path, create=True) as catalog_conn,
        connect(tmp_path / "data" / "run.db", create=True) as run_conn,
    ):
        initialize_catalog(catalog_conn)
        initialize_run(run_conn)
        _seed(settings, catalog_conn, archive_path)
        client = _FakeLlmClient()
        engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=client, settings=settings
        )
        loaded = load(manifest_path)

        first = engine.start(loaded)
        second = engine.start(loaded)

    assert first.run_id != second.run_id
    assert client.calls == 4


def test_request_stop_pauses_then_resume_finishes_the_file(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.ensure_directories()
    archive_path = _build_archive(tmp_path)
    manifest_path = _write_manifest(tmp_path)

    with (
        connect(settings.catalog_database_path, create=True) as catalog_conn,
        connect(tmp_path / "data" / "run.db", create=True) as run_conn,
    ):
        initialize_catalog(catalog_conn)
        initialize_run(run_conn)
        _seed(settings, catalog_conn, archive_path)
        stopping_client = _StoppingLlmClient()
        engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=stopping_client, settings=settings
        )
        stopping_client.engine = engine

        paused = engine.start(load(manifest_path))

        assert paused.interrupted is True
        assert paused.chunks_done == 1
        assert stopping_client.calls == 1
        run = RunsRepository(run_conn).get(paused.run_id)
        assert run is not None
        assert run.status is RunStatus.PAUSED

        resuming_client = _FakeLlmClient()
        resuming_engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=resuming_client, settings=settings
        )
        resumed = resuming_engine.resume(paused.run_id)

        assert resumed.interrupted is False
        assert resumed.chunks_done == 1
        assert resuming_client.calls == 1
        run = RunsRepository(run_conn).get(paused.run_id)
        assert run is not None
        assert run.status is RunStatus.DONE


def test_resume_does_not_rebuild_the_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A resume must not repeat the corpus-wide enqueue scan: the queue already exists.

    Only `start()`'s "fresh run" branch needs `planner.enqueue`; a resumed run's queue was
    already fully populated by the `start()` that created it.
    """
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.ensure_directories()
    archive_path = _build_archive(tmp_path)
    manifest_path = _write_manifest(tmp_path)

    with (
        connect(settings.catalog_database_path, create=True) as catalog_conn,
        connect(tmp_path / "data" / "run.db", create=True) as run_conn,
    ):
        initialize_catalog(catalog_conn)
        initialize_run(run_conn)
        _seed(settings, catalog_conn, archive_path)
        stopping_client = _StoppingLlmClient()
        engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=stopping_client, settings=settings
        )
        stopping_client.engine = engine
        paused = engine.start(load(manifest_path))
        assert paused.interrupted is True

        def _fail(*_args: object, **_kwargs: object) -> int:
            message = "resume() must not call planner.enqueue"
            raise AssertionError(message)

        monkeypatch.setattr(planner, "enqueue", _fail)
        resuming_engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=_FakeLlmClient(), settings=settings
        )
        resumed = resuming_engine.resume(paused.run_id)

        assert resumed.interrupted is False
        assert resumed.chunks_done == 1


def test_a_failing_file_is_marked_as_error_without_aborting_the_run(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", _env_file=None)
    settings.ensure_directories()
    archive_path = _build_archive(tmp_path)
    manifest_path = _write_manifest(tmp_path)

    with (
        connect(settings.catalog_database_path, create=True) as catalog_conn,
        connect(tmp_path / "data" / "run.db", create=True) as run_conn,
    ):
        initialize_catalog(catalog_conn)
        initialize_run(run_conn)
        _seed(settings, catalog_conn, archive_path)
        client = _FailingLlmClient()
        engine = SearchEngine(
            catalog_conn=catalog_conn, run_conn=run_conn, client=client, settings=settings
        )

        outcome = engine.start(load(manifest_path))

    assert outcome.files_done == 1
    assert outcome.chunks_done == 0
    assert outcome.interrupted is False
