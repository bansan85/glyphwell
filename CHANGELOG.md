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

#### Title resolution

- `glyphwell metadata fetch-imdb` and `import-imdb` are operational end to end:
  `fetch-imdb` downloads `title.basics.tsv.gz` and `title.episode.tsv.gz` from the
  official IMDb datasets (no API key, republished daily — ADR-0003); `import-imdb`
  imports them into `titles`, episodes after base titles, and accepts `--source-dir` to
  point at datasets already downloaded and decompressed by hand.
- `metadata/imdb_datasets.py`: `download` (plain streamed download, no resume — these
  files are a few hundred MB at most, unlike the OPUS archive); `locate_dataset` (finds
  either the `.tsv.gz` `download` produces or an already-decompressed `.tsv`); `iter_rows`
  (generic TSV reader, `\N` converted to `None`); `import_basics` and `import_episodes`
  (batched, one transaction per batch of 50 000 rows).
- `metadata/resolver.py`: `Title` (with `display_name()`, e.g. `"Series S01E02 — Title
  (year)"`), the `TitleProvider` protocol, and `SqliteTitleProvider`, which resolves an
  `imdb_id` to a `Title` — including, for an episode, its parent series' title.
- `TitlesRepository` (`get`, `upsert_many`, `set_episode_links_many`, `count`) and
  `ImportsRepository` (traceability of each completed import, one row per pass) in
  `db/repositories.py`. See *Two-pass import* below for why writing an episode's link is
  a distinct operation from writing a title's base columns (ADR-0010).
- **Two-pass import, not a single upsert (ADR-0010).** `import_basics` never knows an
  episode's parent/season/episode, and `import_episodes` never knows the rest of a
  title's columns, including the non-nullable `is_adult`. `TitlesRepository.upsert_many`
  (used only by `import_basics`) coalesces every nullable column so a re-import can't
  blank out a link written by `import_episodes`; the reverse direction goes through
  `set_episode_links_many` (a plain `UPDATE`, not an upsert), which never has to invent a
  value for a column it doesn't have.
- **Performance.** `import_basics`/`import_episodes` read the TSVs positionally
  (`csv.reader`, header resolved once) straight into `TitleRow`/`EpisodeLink`, instead of
  through `csv.DictReader` and a per-row `dict`. Measured on the real `title.basics.tsv`
  (12.7M rows): building and discarding a dict for every row was close to half of the
  total wall-clock time. Combined with a larger batch size (50 000 rows/transaction, up
  from an initial 10 000), throughput went from ~11 400 rows/s to ~50-70 000 rows/s on
  SSD-backed storage — see `doc/metadata.md#performance` for the (larger) effect of disk
  choice on top of this. Confirmed on one real, complete, end-to-end run: all
  12,734,722 rows of `title.basics.tsv` imported and all 9,845,113 `title.episode.tsv`
  links attached.
- **Progress bar for `import-imdb`.** `import_basics`/`import_episodes` accept an
  optional `progress: ProgressCallback` (`Callable[[int, int], None]`, bytes read so
  far and total file size), reported every 50 000 rows through the file's raw binary
  handle so the count stays accurate through gzip decompression. Driven by the file's
  size on disk rather than a row count, which for `title.basics` would mean a full read
  before showing anything. `metadata import-imdb` wires it into a Rich progress bar per
  file, matching `corpus fetch`'s style.
- **No secondary index on `titles` (ADR-0011).** `idx_titles_parent` and
  `idx_titles_type_year`, present in the initial schema, are gone: the only lookup this
  project performs is `imdb_id -> title`, already served by the primary key, and neither
  index's keys correlate with `title.basics.tsv`'s insertion order. Measured on a 4M-row
  real slice: maintaining either one during the bulk import roughly halved throughput
  and made it visibly degrade further as the table grew (a classic
  unsorted-secondary-index-during-bulk-load cost). Removed via a `db/migrations.py`
  version-2 migration, so an already-initialized database is upgraded, not just a fresh
  one. `SelectConfig.title_types`/`years` (`manifest/model.py`) will need a purpose-built
  index back once `search/planner.py` actually implements that prefilter — see ADR-0011
  *Risks*.

#### Full-corpus search

- `glyphwell corpus index` and `glyphwell search run` (including `--dry-run`) are
  operational end to end: the corpus can now be catalogued and scanned by an Ollama
  model, with per-chunk resume.
- `corpus/layout.py`: `normalize_imdb_id`, `parse_entry`, and `iter_corpus` are
  implemented — parsing the six-segment archive path (ADR-0008), rejecting a malformed
  member instead of guessing, and counting/skipping members that don't match instead of
  raising for the whole archive over one bad entry.
- `corpus/reader.py`: `iter_sentences`/`count_sentences` stream an already-open archive
  member (never a `Path` — the archive is never extracted, ADR-0008) through
  `lxml.etree.iterparse(..., recover=True)`, freeing each `<s>` element once visited so
  memory does not grow with the file. `corpus/hashing.py` gained `sha256_stream` for the
  same reason: an archive member has no path on disk to hash from.
- `corpus/chunker.py`: `iter_chunks`/`chunk_count` implement the fixed-stride sliding
  window decided by ADR-0005.
- `manifest/prefilter.py`: `Prefilter` compiles a manifest's patterns once per search
  (literal patterns `re.escape`-d, folding literal and regex matching into one code path)
  and evaluates `any`/`all`/`none`/`off` against a chunk's rendered text.
- `ollama/prompts.py`: `render`/`render_context` substitute a chunk's `{{ title / year /
  imdb_id / first_id / last_id / chunk }}` placeholders, raising `ManifestError` on an
  unknown one rather than sending a truncated prompt to thousands of chunks.
- `ollama/client.py`: `OllamaClient`, backed by the `ollama` package, implements
  `LlmClient.complete` (schema-constrained generation, decoded and re-checked
  client-side — ADR-0013) and `ensure_model` (fails a run before it starts scanning the
  corpus rather than partway through it), with retry/backoff on transient failures and
  immediate failure on a request the server itself rejects.
- `search/engine.py`, `search/planner.py`, `search/checkpoint.py`: the full
  orchestration — deterministic queue (`ORDER BY rel_path`), per-chunk commit
  (`commit_chunk`, one transaction per chunk), and cross-file concurrency bounded by
  `Settings.concurrency`, with worker threads confined to the Ollama call itself
  (ADR-0012). A prefiltered-out chunk still gets a `commit_chunk` call (`matched=False,
  payload=None`) so `results` stays a gapless ledger of every `chunk_index` for a file.
  Clean SIGINT handling: the current chunk finishes and commits before the run is marked
  `paused`.
- `search run` now reports progress instead of going silent between the initial
  `database opened` line and the final summary table: run creation/resume and queue size
  at `INFO`, one line per file completed at `INFO`, and one line per chunk (submitted,
  pre-filtered, or committed with its match/latency) at `DEBUG`. `ollama/client.py` logs
  each call's latency at `DEBUG` and now logs a retry attempt at `WARNING` instead of
  sleeping through the backoff with no visible cause.
- `search/results.py`: `validate_output` re-checks a response against the manifest's
  schema and resolves `match_when`, independently of the `format` constraint already
  requested from Ollama (ADR-0013).
- `SubtitleFilesRepository`, `RunsRepository`, `RunFilesRepository`, and
  `ResultsRepository` (`db/repositories.py`) are now implemented, alongside two additions
  the engine needed beyond the original stub signatures: `SubtitleFilesRepository.get`
  and `RunsRepository.get_manifest_snapshot` (a dedicated lookup, so listing runs doesn't
  load every archived YAML body).
- `searches/example.yaml` gained a worked example (`ski_pistes`): a full
  `select`/`chunk`/`prefilter`/`prompt`/`output` manifest that doubles as regression
  coverage for the manifest format (`test_loads_example_manifest`).

#### Documentation

- `doc/` holds the user-facing documentation: `index.md`, `installation.md`,
  `configuration.md`, `corpus.md`, `metadata.md`, and `search.md` (step 3: cataloguing
  the corpus, the manifest format, `--dry-run`, concurrency, troubleshooting).
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
- **The per-file freshness checksum** (ADR-0006, superseded by ADR-0015):
  `subtitle_files.sha256`, `run_files.file_sha256`, `corpus index --rehash`, the now-empty
  `corpus refresh` stub, and the repository methods that only served them
  (`SubtitleFilesRepository.set_hash`/`iter_stale`, `RunFilesRepository.reset`,
  `ResultsRepository.delete_for_file`). `opus_version` already makes a new OPUS release a
  new `subtitle_files` row, and a changed subtitle arrives under a new
  `opensubtitles_file_id` rather than mutating an existing one, so the checksum never
  caught anything real; nothing had wired `run_files.file_sha256` or called the other two
  repository methods in the first place. `corpus index` no longer reads any subtitle
  content — pure central-directory cataloging. `db/schema.sql` drops both columns;
  `db/migrations.py` version 3 does the same on an existing database. The archive-download
  checksum (`corpus_downloads.sha256`, `corpus fetch --hash`) and the manifest hash
  (`runs.manifest_hash`) are untouched — unrelated concepts.

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
- **A title starting with a literal `"` was silently corrupted on import.** About 5 500
  rows of `title.basics.tsv` have a `primaryTitle` that literally starts with `"` (e.g.
  `"Giliap"`, a real 1975 film) — IMDb's datasets are not CSV-quoted. Python's default
  `csv` dialect treats a leading `"` as opening a quoted field and silently strips it;
  `iter_rows` now reads with `quoting=csv.QUOTE_NONE`.
- **`corpus index`'s progress bar never reached 100%.** It was sized off
  `ArchiveSummary.subtitle_count` (every `.xml` member, any language) but only advanced
  per batch of entries `iter_corpus` actually yielded, which excludes members outside the
  requested language and ones that fail the layout check — on a real archive, several
  hundred thousand members short of the total. `iter_corpus` now takes an optional
  `on_member` callback, called once per member visited regardless of outcome, and
  `_catalog` drives the bar from it instead of from batch sizes.
- **`corpus index` silently dropped every TV episode.** The layout's `imdb_id` segment is
  bare only for movies; for a TV episode OPUS packs four underscore-separated fields into
  it instead (`<episode_id>_<series_id>_<season>_<episode>`), which
  `normalize_imdb_id`'s bare-digits check rejected as unparsable — on the real
  `v2024`/`raw`/`en` archive, 64.5% of subtitle members. `normalize_imdb_id` now
  recognizes the compound form and keeps the episode's own id, discarding the embedded
  series id/season/episode as a scrape-time copy of data the IMDb datasets already own
  (ADR-0016).
- **`search run`'s work-queue construction generated one SQLite transaction per file and
  blocked its own WAL checkpoint.** `enqueue_many`'s batched `INSERT OR IGNORE` calls ran
  with no explicit transaction, so on the autocommit connection every file became its own
  commit; the enclosing `SELECT` cursor also stayed open across all of them, and in WAL
  mode an open reader pins the checkpoint to the point its snapshot began, so none of
  those writes could ever be reclaimed either. On a real ~1.3M-file corpus this grew the
  WAL to several times the size of the main database and slowed down every subsequent
  read. `planner.enqueue` now paginates the matching query with keyset pagination on
  `sf.file_id`, draining and closing each page's cursor before writing it in its own
  explicit transaction. `SearchEngine` also no longer re-runs this scan on every resume —
  only a freshly created run needs it, since a resume's queue was already fully populated
  by the `start()` that created it. `db/connection.py` additionally raises the page cache
  from SQLite's ~2 MB default to 256 MiB and checkpoints (`PRAGMA wal_checkpoint(TRUNCATE)`)
  the WAL when a connection closes, so it no longer accumulates across invocations.

All seven defects are covered by regression tests.

### Public API

The following names are exported and stable in shape. Most of the callables behind them
are now implemented; see *Known limitations* for the handful that still raise
`NotImplementedError`.

| Module | Exported names |
|---|---|
| `glyphwell` | `__version__` |
| `glyphwell.types` | `ImdbId`, `JsonObject`, `JsonValue`, `LanguageCode`, `OpenSubtitlesFileId`, `OpusVersion`, `SentenceId`, `Sha256` |
| `glyphwell.config` | `LogLevel`, `Settings` |
| `glyphwell.errors` | `GlyphwellError`, `ConfigurationError`, `CorpusError`, `CorpusLayoutError`, `CorpusReadError`, `DatabaseError`, `ManifestError`, `MetadataError`, `ModelOutputError`, `OllamaError`, `SchemaVersionError`, `SearchError` |
| `glyphwell.console` | `console` |
| `glyphwell.logging` | `get_logger`, `setup_logging` |
| `glyphwell.cli` | `AppContext`, `app`, `get_context`, `main` |
| `glyphwell.corpus` | `ArchiveMember`, `ArchiveSummary`, `Chunk`, `CorpusArchive`, `CorpusEntry`, `Sentence`, `chunk_count`, `count_sentences`, `iter_chunks`, `iter_corpus`, `iter_sentences`, `normalize_imdb_id`, `parse_entry`, `sha256_file`, `sha256_stream` |
| `glyphwell.corpus.archive` | `ArchiveMember`, `ArchiveSummary`, `CorpusArchive` |
| `glyphwell.corpus.opus` | `DEFAULT_CORPUS`, `DEFAULT_PREPROCESSING`, `DEFAULT_TIMEOUT`, `DEFAULT_VERSION`, `CorpusDownload`, `OpusFileRecord`, `Preprocessing`, `ProgressCallback`, `download_corpus`, `iter_available_versions`, `resolve_archive` |
| `glyphwell.corpus.layout` | `IMDB_ID_WIDTH`, `SUBTITLE_SUFFIXES`, `CorpusEntry`, `iter_corpus`, `normalize_imdb_id`, `parse_entry` |
| `glyphwell.corpus.reader` | `Sentence`, `count_sentences`, `iter_sentences` |
| `glyphwell.corpus.chunker` | `Chunk`, `chunk_count`, `iter_chunks` |
| `glyphwell.corpus.hashing` | `DEFAULT_CHUNK_SIZE`, `sha256_file`, `sha256_stream` |
| `glyphwell.db` | `SCHEMA_VERSION`, `connect`, `current_version`, `ensure_current`, `initialize`, `open_connection`, `schema_sql` |
| `glyphwell.db.repositories` | `CorpusDownloadRow`, `CorpusDownloadsRepository`, `DownloadStatus`, `EpisodeLink`, `FileStatus`, `ImportRow`, `ImportSource`, `ImportsRepository`, `RunStatus`, `ResultRow`, `ResultsRepository`, `RunFileRow`, `RunFilesRepository`, `RunRow`, `RunsRepository`, `SubtitleFileRow`, `SubtitleFilesRepository`, `TitleRow`, `TitlesRepository` |
| `glyphwell.manifest` | `LoadedManifest`, `Prefilter`, `SearchManifest`, `load`, `manifest_hash` |
| `glyphwell.manifest.model` | `ChunkConfig`, `OutputConfig`, `OutputFormat`, `PrefilterConfig`, `PrefilterMode`, `PromptConfig`, `SearchManifest`, `SelectConfig`, `YearRange` |
| `glyphwell.metadata` | `ImdbDataset`, `SqliteTitleProvider`, `Title`, `TitleProvider` |
| `glyphwell.metadata.imdb_datasets` | `BASE_URL`, `NULL_MARKER`, `ImdbDataset`, `ProgressCallback`, `download`, `import_basics`, `import_episodes`, `iter_rows`, `locate_dataset` |
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
                    index [--language]
glyphwell metadata  fetch-imdb [--force] | import-imdb [--source-dir]
glyphwell search    run [--limit --concurrency --dry-run] | resume | status | export
```

### Known limitations

- 5 call sites across 2 modules raise `NotImplementedError` (down from 6 across 3, itself
  down from 56 across 13, itself down from 68 across 16 — `corpus refresh` is gone rather
  than staying a stub, see ADR-0015). Signatures, dataclasses and protocols are complete
  and typecheck under strict mypy, but the bodies are not written. Fully working at this
  point: `db init`, `db status`, `db vacuum`, `corpus fetch`, `corpus index`,
  `metadata fetch-imdb`, `metadata import-imdb`, `search run` (including `--dry-run`),
  manifest loading/validation/hashing, sha256 computation, configuration and logging.
- `search resume`/`status`/`export` still raise: everything downstream of a finished run
  (`search/results.py`'s `export_run` and `summary`) remains out of scope. Every
  repository in `db/repositories.py` is now implemented.
- **`SelectConfig.title_types`/`years` filtering is live without the index ADR-0011 said
  it would need.** `search/planner.py::_matching_query` now joins `subtitle_files` to
  `titles` and filters on `t.title_type`/`t.start_year` exactly as ADR-0011 anticipated,
  but no migration adding a purpose-built index has landed with it —
  `db/migrations.py` and `db/schema.sql` are unchanged by this commit. Whether this
  matters depends on the query plan SQLite picks: driving off `subtitle_files` and
  reaching `titles` by primary key needs no such index; driving off a
  `title_type`/`start_year`-filtered scan of `titles` would. Measure with
  `EXPLAIN QUERY PLAN` on a populated database before assuming either way, and add the
  migration ADR-0011 already described if it turns out to matter.
- **`Settings.concurrency` is bounded twice (ADR-0012).** Raising it past what the Ollama
  server can actually run in parallel — `OLLAMA_NUM_PARALLEL`, and the model's fit in
  available VRAM — buys nothing: a single, VRAM-constrained GPU serializes the underlying
  compute regardless of how many chunks the engine hands it at once.
- **No measurement of a model's schema-compliance rate before a long run (ADR-0013).**
  `ensure_model` only checks that the model is present, not that it reliably honors
  `output.schema`; a model with a high violation rate turns into a high per-file error
  rate discovered mid-run rather than a preflight check.
- **No incremental resume for the IMDb import.** Unlike the search engine's per-chunk
  resume (ADR-0005), `import_basics`/`import_episodes` keep no cursor: an interruption is
  safe (the batch in progress is rolled back, upsert makes replaying it a no-op) but a
  rerun always restarts from the first row of the file, re-processing everything already
  imported. Acceptable for a periodic, one-off catalogue refresh; would need a real fix
  before running unattended on a schedule.
- **`SqliteTitleProvider.resolve_many` is not batched.** It calls `resolve()` — two
  single-row lookups (the title, then its parent if it's an episode) — once per
  identifier, rather than issuing one query for the whole batch. Simple and correct, but
  a caller resolving hundreds of thousands of identifiers at once (e.g. the whole corpus)
  pays one SQLite round trip per identifier instead of a handful of batched ones.
- **A dropped episode link fails silently.** See ADR-0010 *Risks*: if `import_episodes`
  runs for a `tconst` that `import_basics` has not written yet, the `UPDATE` matches zero
  rows and the link is lost without an error. `import-imdb` always runs the two passes in
  the right order, but nothing currently compares "links attempted" against
  `set_episode_links_many`'s returned count to surface a partial run.
- **Import throughput is largely disk-bound, and no code change fixes that.** Measured on
  the development machine: the same optimized code reached ~50-70 000 rows/s with the
  database on an SSD, but only ~9 700 rows/s — barely above the pre-optimization
  baseline — with the database on a mechanical HDD (measured before ADR-0011's index
  removal; removing them narrows this gap but does not close it, since disk commit
  latency is not an indexing cost). See `doc/metadata.md#performance`.
- **Some schema changes still predate any version bump.** `SCHEMA_VERSION` is now `2`
  (the index removal above is `db/migrations.py`'s first real migration), but two
  earlier renames — `subtitle_files.opus_file_id` to `opensubtitles_file_id` and
  `corpus_downloads.extracted_at` to `verified_at` — were made directly in `schema.sql`
  while it was still "version 1" and have no corresponding migration. A database
  created before those renames passes `ensure_current` and then fails at runtime on a
  missing column. Delete `data/glyphwell.db` and run `glyphwell db init` again. Acceptable
  only because `data/` is gitignored and fully reconstructible, and nothing is released.
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
- ADR-0006 — detect staleness with the pair `(opus_version, sha256)` (superseded by
  ADR-0015)
- ADR-0007 — enforce very strict typing with no escape hatches
- ADR-0008 — never extract the corpus archive
- ADR-0009 — use opustools as the OPUS index only, and httpx for the transfer
- ADR-0010 — two-pass IMDb import: coalescing upsert plus a dedicated episode-link update
- ADR-0011 — drop the secondary indexes on `titles`
- ADR-0012 — cross-file concurrency with thread-confined SQLite access
- ADR-0013 — re-validate the model's JSON output client-side
- ADR-0014 - one http client factory and a bounded TLS escape hatch
- ADR-0015 — drop the per-file freshness checksum
- ADR-0016 — keep only the episode id from the TV-episode compound segment
