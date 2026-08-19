# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Nothing has been released yet. `__version__` is `0.1.0` and no tag exists, so all entries
below sit under `Unreleased`.

## [Unreleased]

### Added

#### Packaging and tooling

- `pyproject.toml` following PEP 621, built with `hatchling`, `src/` layout, `uv.lock`
  committed for reproducible environments (ADR-0001).
- Console entry point `glyphwell`, plus `python -m glyphwell`.
- ruff for linting and formatting, mypy in very strict mode over `src` and `tests` with no
  per-module overrides (ADR-0007), pytest, pre-commit hooks, and a GitHub Actions workflow
  running the same gate on Linux and Windows.
- Local type stubs under `stubs/` for `opustools`, which ships no type information.

#### Database

- SQLite schema in `src/glyphwell/db/schema.sql`, version 1, carried by
  `PRAGMA user_version`. Deliberately no FTS5: subtitle text is neither copied nor indexed
  (ADR-0002).
- Tables: `titles`, `subtitle_files`, `runs`, `run_files`, `results`, `corpus_downloads`,
  `imports`.
- `glyphwell db init` creates a valid database; `db status` reports the schema version and
  row counts; `db vacuum` compacts it.

#### Search manifests

- YAML manifest format for defining a search, validated by pydantic v2 and identified by
  the SHA-256 of its normalised content (ADR-0004). Line endings are normalised before
  hashing so a checkout does not change the identity of a run.
- Commented example in `searches/example.yaml`.

#### Configuration, logging, errors

- `Settings` built on pydantic-settings, reading `GLYPHWELL_*` environment variables and
  `.env`; documented in `.env.example`.
- Logging set up over the standard library with a Rich handler.
- Exception hierarchy rooted at `GlyphwellError`.

### Public API

The following names are exported and stable in shape. Most of the callables behind them
raise `NotImplementedError` at this stage; see *Known limitations*.

| Module | Exported names |
|---|---|
| `glyphwell` | `__version__` |
| `glyphwell.types` | `ImdbId`, `JsonObject`, `JsonValue`, `LanguageCode`, `OpusFileId`, `OpusVersion`, `SentenceId`, `Sha256` |
| `glyphwell.config` | `LogLevel`, `Settings` |
| `glyphwell.errors` | `GlyphwellError`, `ConfigurationError`, `CorpusError`, `CorpusLayoutError`, `CorpusReadError`, `DatabaseError`, `ManifestError`, `MetadataError`, `ModelOutputError`, `OllamaError`, `SchemaVersionError`, `SearchError` |
| `glyphwell.logging` | `get_logger`, `setup_logging` |
| `glyphwell.cli` | `AppContext`, `app`, `get_context`, `main` |
| `glyphwell.corpus` | `Chunk`, `CorpusEntry`, `Sentence`, `chunk_count`, `count_sentences`, `iter_chunks`, `iter_corpus`, `iter_sentences`, `normalize_imdb_id`, `parse_entry`, `sha256_file` |
| `glyphwell.corpus.opus` | `DEFAULT_CORPUS`, `DEFAULT_PREPROCESSING`, `DEFAULT_VERSION`, `CorpusDownload`, `Preprocessing`, `download_corpus`, `extract_archive`, `iter_available_versions` |
| `glyphwell.corpus.layout` | `IMDB_ID_WIDTH`, `SUBTITLE_SUFFIXES`, `CorpusEntry`, `iter_corpus`, `normalize_imdb_id`, `parse_entry` |
| `glyphwell.corpus.reader` | `Sentence`, `count_sentences`, `iter_sentences` |
| `glyphwell.corpus.chunker` | `Chunk`, `chunk_count`, `iter_chunks` |
| `glyphwell.corpus.hashing` | `DEFAULT_CHUNK_SIZE`, `sha256_file` |
| `glyphwell.db` | `SCHEMA_VERSION`, `connect`, `current_version`, `ensure_current`, `initialize`, `open_connection`, `schema_sql` |
| `glyphwell.db.repositories` | `FileStatus`, `RunStatus`, `ResultRow`, `ResultsRepository`, `RunFileRow`, `RunFilesRepository`, `RunRow`, `RunsRepository`, `SubtitleFileRow`, `SubtitleFilesRepository`, `TitleRow`, `TitlesRepository` |
| `glyphwell.manifest` | `LoadedManifest`, `Prefilter`, `SearchManifest`, `load`, `manifest_hash` |
| `glyphwell.manifest.model` | `ChunkConfig`, `OutputConfig`, `OutputFormat`, `PrefilterConfig`, `PrefilterMode`, `PromptConfig`, `SearchManifest`, `SelectConfig`, `YearRange` |
| `glyphwell.metadata` | `ImdbDataset`, `SqliteTitleProvider`, `Title`, `TitleProvider` |
| `glyphwell.metadata.imdb_datasets` | `BASE_URL`, `NULL_MARKER`, `ImdbDataset`, `download`, `import_basics`, `import_episodes`, `iter_rows` |
| `glyphwell.ollama` | `Completion`, `LlmClient`, `OllamaClient`, `PromptContext`, `render`, `render_context` |
| `glyphwell.ollama.prompts` | `PLACEHOLDERS`, `PromptContext`, `render`, `render_context` |
| `glyphwell.search` | `Checkpoint`, `ExportFormat`, `PlannedFile`, `SearchEngine`, `SearchOutcome`, `ValidatedOutput`, `commit_chunk`, `enqueue`, `export_run`, `iter_work`, `load_checkpoint`, `validate_output` |
| `glyphwell.search.checkpoint` | `Checkpoint`, `commit_chunk`, `load_checkpoint`, `resume_position` |
| `glyphwell.search.planner` | `PlannedFile`, `enqueue`, `iter_work`, `plan_size` |
| `glyphwell.search.results` | `ExportFormat`, `ValidatedOutput`, `export_run`, `validate_output` |

Note that `resume_position` and `plan_size` are exported by their own modules but not
re-exported from the `glyphwell.search` package.

#### Command-line interface

```
glyphwell [--version] [--data-dir] [--database] [--log-level]
glyphwell db        init | status | vacuum
glyphwell corpus    fetch | index | refresh
glyphwell metadata  fetch-imdb | import-imdb
glyphwell search    run | resume | status | export
```

### Known limitations

- 72 call sites across 17 modules raise `NotImplementedError`. Signatures, dataclasses and
  protocols are complete and typecheck under strict mypy, but the bodies are not written.
  Fully working at this point: `db init`, `db status`, `db vacuum`, manifest loading,
  validation and hashing, sha256 computation, configuration and logging.
- The command bodies of `corpus`, `metadata` and `search` raise; only the `db` group is
  operational.
- The corpus directory layout assumed by `corpus/layout.py`
  (`<language>/<year>/<imdb_id>/<opus_file_id>.xml`, with a bare zero-padded IMDb id) is
  inferred from usage and is not documented by OPUS. It is isolated behind two functions and
  covered by a sample test, and must be confirmed after the first real `corpus fetch`.
- No `LICENSE` file yet.

### Decisions recorded

Architecture Decision Records live in [docs/adr/](docs/adr/):

- ADR-0001 — use uv for packaging and dependency management
- ADR-0002 — store the catalogue and run state in SQLite without FTS5
- ADR-0003 — use the official IMDb datasets as the sole metadata source
- ADR-0004 — define a search with a hashed YAML manifest
- ADR-0005 — analyse sliding windows of sentences and resume inside a file
- ADR-0006 — detect staleness with the pair `(opus_version, sha256)`
- ADR-0007 — enforce very strict typing with no escape hatches
