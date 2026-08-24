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

#### Corpus acquisition

- `glyphwell corpus fetch` is operational end to end: it resolves the archive in the OPUS
  index, announces the URL and the announced size before transferring anything, downloads
  with a resumable stream, verifies the archive and records the acquisition in
  `corpus_downloads`.
- `corpus/opus.py`: `resolve_archive` picks the monolingual record for one corpus, release,
  language and preprocessing; `download_corpus` streams it with `httpx` into a `.part` file
  resumed through an HTTP `Range` header and renamed only once complete;
  `iter_available_versions` lists the releases the index declares (ADR-0009).
- `corpus/archive.py`: `CorpusArchive` reads the zip member by member, decompressing on the
  fly and never extracting anything (ADR-0008). `summarize()` walks the central directory
  once to count subtitles, service files and members with an unexpected suffix, and samples
  a few member names so the real internal layout is visible after a download.
- `sha256` is computed as the bytes stream past when a transfer starts from zero; after a
  resume it is reported as not computed, and `--hash` forces a separate pass.
- `CorpusDownloadsRepository` with `DownloadStatus` and `CorpusDownloadRow`: the row is
  written as `pending` before the transfer starts, so a missing database fails the command
  immediately rather than after tens of gigabytes.
- `glyphwell.console` exposes the single Rich `Console` shared by the commands and by the
  logging handler.

#### Documentation

- `doc/` holds the user-facing documentation: `index.md`, `installation.md`,
  `configuration.md`, and `corpus.md` covering releases, resume, the internal layout of the
  archive, traceability and troubleshooting.
- `README.md` gained a quick-start section with a real transcript.

### Changed

Nothing has been released, so these are corrections to entries described above rather than
breaking changes for users. They do change names that were already committed.

- **`OpusFileId` is now `OpenSubtitlesFileId`.** The last path segment of a corpus member is
  the identifier of a subtitle on opensubtitles.org, not an OPUS identifier: it designates
  one *translation*, where `ImdbId` designates the *work*. The rename reaches
  `glyphwell.types`, `CorpusEntry`, `SubtitleFileRow` and the `subtitle_files` column.
- **The internal layout of the archive is now known**, including the prefix it was missing:
  `<corpus>/<preprocessing>/<language>/<year>/<imdb_id>/<opensubtitles_file_id>.xml`.
  `subtitle_files.rel_path` now stores the **full member name, prefix included**, because it
  is the only key `CorpusArchive.open_member()` accepts.
- `iter_corpus` takes an open `CorpusArchive` instead of a directory root.
- `SUBTITLE_SUFFIXES` is `(".xml",)`. The skeleton also listed `".xml.gz"`, which was an
  assumption, not an observation; members with an unexpected suffix are now counted and
  reported instead.
- `subtitle_files.opus_file_id` became `opensubtitles_file_id`, and
  `corpus_downloads.extracted_at` became `verified_at` (the archive is verified, never
  extracted). `PRAGMA user_version` stays at 1 and `_MIGRATIONS` stays empty; see
  *Known limitations*.
- Default OPUS release is `v2024` instead of `v2018`, in `Settings.opus_version`,
  `DEFAULT_VERSION` and `.env.example`. It is the most recent and most complete release:
  35.8 GB for `en` / `raw`, against 13.7 GB for `v2018`.
- `Settings.corpus_dir` now holds the archive itself, one zip per (release, language), not
  an extracted tree. `Settings.downloads_dir` is left to the IMDb TSV files.
- `corpus fetch --dest` is the directory the archive is written to, and a new `--hash`
  option forces the fingerprint when the transfer could not produce it for free.
- `stubs/opustools/__init__.pyi` was rewritten against `opustools` 1.8.3 and reduced to the
  surface actually used: `OpusGet.url` and `OpusGet.make_file_name`.

### Removed

- `corpus.opus.extract_archive`, along with the `extracted` download status and the
  `extracted_at` column. Nothing is extracted any more (ADR-0008).
- `OpusRead`, `get_files` and `get_corpora_data` from the `opustools` stub: no caller left,
  and the declared signatures of the last two were wrong.

### Fixed

- **A query for one language could download the archive of another.** In `raw`
  preprocessing the OPUS index returns the monolingual archive of every language paired with
  the requested one — 51 candidates for `en` — so filtering on `target == ""` alone was not
  enough. The filter now also requires `source == language`.
- **`iter_available_versions` always returned an empty list.** The "single space" wildcard
  suggested by `opustools` is sent as an empty `version=`, which the live API reads as
  "no version". The parameter is now omitted instead.
- **Log lines emitted during a download corrupted the progress bar.** `RichHandler()` with
  no argument writes to Rich's global console, which is not the one the `Progress` renders
  on; only prints on the live display's own console go through its render hook. Both now
  share `glyphwell.console.console`.

Both index defects are covered by regression tests.

### Public API

The following names are exported and stable in shape. Most of the callables behind them
raise `NotImplementedError` at this stage; see *Known limitations*.

| Module | Exported names |
|---|---|
| `glyphwell` | `__version__` |
| `glyphwell.types` | `ImdbId`, `JsonObject`, `JsonValue`, `LanguageCode`, `OpenSubtitlesFileId`, `OpusVersion`, `SentenceId`, `Sha256` |
| `glyphwell.config` | `LogLevel`, `Settings` |
| `glyphwell.errors` | `GlyphwellError`, `ConfigurationError`, `CorpusError`, `CorpusLayoutError`, `CorpusReadError`, `DatabaseError`, `ManifestError`, `MetadataError`, `ModelOutputError`, `OllamaError`, `SchemaVersionError`, `SearchError` |
| `glyphwell.console` | `console` |
| `glyphwell.logging` | `get_logger`, `setup_logging` |
| `glyphwell.cli` | `AppContext`, `app`, `get_context`, `main` |
| `glyphwell.corpus` | `ArchiveMember`, `ArchiveSummary`, `Chunk`, `CorpusArchive`, `CorpusEntry`, `Sentence`, `chunk_count`, `count_sentences`, `iter_chunks`, `iter_corpus`, `iter_sentences`, `normalize_imdb_id`, `parse_entry`, `sha256_file` |
| `glyphwell.corpus.archive` | `ArchiveMember`, `ArchiveSummary`, `CorpusArchive` |
| `glyphwell.corpus.opus` | `DEFAULT_CORPUS`, `DEFAULT_PREPROCESSING`, `DEFAULT_TIMEOUT`, `DEFAULT_VERSION`, `CorpusDownload`, `OpusFileRecord`, `Preprocessing`, `ProgressCallback`, `download_corpus`, `iter_available_versions`, `resolve_archive` |
| `glyphwell.corpus.layout` | `IMDB_ID_WIDTH`, `SUBTITLE_SUFFIXES`, `CorpusEntry`, `iter_corpus`, `normalize_imdb_id`, `parse_entry` |
| `glyphwell.corpus.reader` | `Sentence`, `count_sentences`, `iter_sentences` |
| `glyphwell.corpus.chunker` | `Chunk`, `chunk_count`, `iter_chunks` |
| `glyphwell.corpus.hashing` | `DEFAULT_CHUNK_SIZE`, `sha256_file` |
| `glyphwell.db` | `SCHEMA_VERSION`, `connect`, `current_version`, `ensure_current`, `initialize`, `open_connection`, `schema_sql` |
| `glyphwell.db.repositories` | `CorpusDownloadRow`, `CorpusDownloadsRepository`, `DownloadStatus`, `FileStatus`, `RunStatus`, `ResultRow`, `ResultsRepository`, `RunFileRow`, `RunFilesRepository`, `RunRow`, `RunsRepository`, `SubtitleFileRow`, `SubtitleFilesRepository`, `TitleRow`, `TitlesRepository` |
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

`CorpusEntry.opus_file_id` is now `CorpusEntry.opensubtitles_file_id`, and `iter_corpus`
takes an open `CorpusArchive` rather than a directory root.

#### Command-line interface

```
glyphwell [--version] [--data-dir] [--database] [--log-level]
glyphwell db        init | status | vacuum
glyphwell corpus    fetch [--language --version --corpus --dest --force --hash]
                    index | refresh
glyphwell metadata  fetch-imdb | import-imdb
glyphwell search    run | resume | status | export
```

### Known limitations

- 68 call sites across 16 modules raise `NotImplementedError`. Signatures, dataclasses and
  protocols are complete and typecheck under strict mypy, but the bodies are not written.
  Fully working at this point: `db init`, `db status`, `db vacuum`, `corpus fetch`, manifest
  loading, validation and hashing, sha256 computation, configuration and logging.
- `corpus index`, `corpus refresh`, and the whole `metadata` and `search` groups still
  raise. `CorpusDownloadsRepository` is the only repository implemented.
- **The schema changed shape without a version bump.** `subtitle_files.opus_file_id` became
  `opensubtitles_file_id` and `corpus_downloads.extracted_at` became `verified_at`, while
  `SCHEMA_VERSION` stays at 1 and `_MIGRATIONS` stays empty. A database created before this
  change therefore passes `ensure_current` and then fails at runtime on a missing column.
  Delete `data/glyphwell.db` and run `glyphwell db init` again. This is acceptable only
  because `data/` is gitignored and fully reconstructible, and nothing is released.
- `SubtitleFileRow.file_id` is typed `int`, so `SubtitleFilesRepository.upsert` cannot be
  handed a row that has not been inserted yet. `CorpusDownloadRow.download_id` is
  `int | None` and does not have the defect; the other row types were left as they were.
- The internal layout of the archive is established from a directly observed member name,
  but the English `v2024` archive itself has not been walked. `corpus fetch` prints a few
  member names and counts members whose suffix is outside `SUBTITLE_SUFFIXES`, so the first
  full download settles it; a non-zero count means `corpus/layout.py` needs revisiting.
- `corpus fetch` has no end-to-end test. The Typer command offers no seam to inject an HTTP
  client, so the library layer is covered directly with `httpx.MockTransport` and the
  command wiring is not covered at all.
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
- ADR-0008 — never extract the corpus archive
- ADR-0009 — use opustools as the OPUS index only, and httpx for the transfer
