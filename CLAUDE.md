# CLAUDE.md

Working memory for the `glyphwell` project. Records what **can't be derived from the
code**: intent, pitfalls of external data sources, and the invariants the program's
correctness depends on.

## 1. Purpose

Search the entirety of the OpenSubtitles subtitle corpus using a local LLM.
Four target capabilities:

1. **Download** the OPUS *OpenSubtitles* corpus (language `en`, format `raw`) via `opustools`.
2. **Title resolution** for movies / series / episodes from the IMDb ids carried by the
   corpus tree.
3. **Search** across the whole corpus, driven by a YAML manifest, executed by Ollama.
4. **Resume** an interrupted search *in the middle of a subtitle file* and **re-analyze**
   files for which a newer version has been published.

English is used because it's the language OpenSubtitles covers best.

## 2. Language

All source code is written in English: identifiers, comments, docstrings, log messages,
CLI help text and other user-facing strings, and generated documentation — including this
file and everything under `doc/` and `README.md`.

The only exception is the live conversation between the user and Claude Code: reply in
whichever language the user writes in, turn by turn, even while the task itself (code,
commits, docs) stays English-only. Don't let the task's working language bleed into the
conversation.

## 3. Commands

**Everything goes through `uv`** (never `pip install` directly into `.venv`, or `uv.lock`
and the environment would drift apart).

```bash
uv sync --all-extras           # install / update the environment
uv run glyphwell --help        # CLI
uv run pytest -q
uv run ruff check . && uv run ruff format .
uv run mypy                    # `files` is fixed in pyproject: src + tests
```

## 4. Style and typing

Modern Python 3.12:

- Native unions `str | None` — never `Optional` / `Union`.
- Builtin generics (`list[str]`, `dict[str, int]`); abstractions from
  `collections.abc` (`Iterator`, `Sequence`, `Mapping`, `Callable`).
- PEP 695 type aliases in [types.py](src/glyphwell/types.py): `type ImdbId = str`, etc.
  They document intent at zero runtime cost.
- Value objects: `@dataclass(frozen=True, slots=True, kw_only=True)`.
  Data coming from the outside (YAML, LLM JSON): pydantic v2 models.
- Interfaces: `Protocol`, no inheritance — test doubles have nothing to subclass.
- Closed statuses: `StrEnum`, exhaustiveness checked with `assert_never`.
- `pathlib.Path` everywhere, never a path as `str`. `Final` for module-level constants.
- **Generators are mandatory** for anything large (XML reading, TSV import, corpus
  traversal). The corpus doesn't fit in memory — never a top-level `list(...)`.
- Annotate public signatures systematically; locally, annotate only what mypy can't infer
  (empty collections, untyped boundaries, `Final`).

mypy is configured in **very strict mode** in `pyproject.toml`. Rules to keep in mind:

- **No `Any`.** `disallow_any_explicit` forbids the `Any` annotation. At untyped
  boundaries (`yaml.safe_load`, the model's JSON response) annotate `object`, then narrow
  immediately via pydantic or explicit narrowing. The JSON payload type is
  `JsonValue` / `JsonObject`, re-exported from pydantic in `types.py`.
- **No bare `# type: ignore`.** `ignore-without-code` requires `# type: ignore[code]`, and
  `warn_unused_ignores` flags ignores that have become unnecessary.
- `disallow_any_unimported` forbids `ignore_missing_imports`: an untyped dependency
  requires a local stub under [stubs/](stubs/). That's the case for `opustools`
  ([stubs/opustools/__init__.pyi](stubs/opustools/__init__.pyi)) — declare only the
  surface actually used there.
- **No per-module override.** There is deliberately no
  `[[tool.mypy.overrides]]` section: the strict configuration applies as-is to `src/` and
  `tests/` alike, Typer decorators and pytest included. If a future dependency forces an
  override, scope it to that module and explain why here.

Four pitfalls hit already, not to be reintroduced:

- **PEP 695 and Typer.** Typer introspects annotations at runtime and can't unwrap a
  `TypeAliasType`. A `type X = Literal[...]` used in a command signature breaks the CLI's
  construction (`RuntimeError: Type not yet supported`). Hence the implicit alias
  `LogLevel = Literal[...]` in [config.py](src/glyphwell/config.py). Pydantic, on the other
  hand, handles PEP 695 aliases just fine: the general rule stays PEP 695, with this
  exception documented in place.
- **Pydantic's mypy plugin.** `init_typed = true` forbids `Settings(**overrides)`: unpacking
  a dict isn't type-checkable. Build the object with explicit keywords instead (see the
  root callback in [cli/__init__.py](src/glyphwell/cli/__init__.py)).
- **CLI import cycle.** `AppContext` and `get_context` live in
  [cli/context.py](src/glyphwell/cli/context.py), not in `cli/__init__.py`: subcommand
  modules depend on them, and `cli/__init__.py` depends on their `Typer` instances.
  Importing them from the package would create a cycle that mypy reports as
  `Cannot determine type of "app"`.
- **A single Rich `Console`.** It lives in [console.py](src/glyphwell/console.py) and
  nothing else constructs one — not the subcommands, not the `RichHandler` in
  [logging.py](src/glyphwell/logging.py), which receives it explicitly. Rich can only
  coordinate a live display (`Progress`, `Live`) with ordinary writes when both go through
  the *same* instance: each one otherwise keeps its own cursor position. With two consoles,
  the smallest log line emitted during a download gets written right over the progress bar.
  `RichHandler()` with no argument grabs Rich's global console — that's exactly the trap.

## 5. Data sources and their pitfalls

### OPUS OpenSubtitles corpus (`opustools`)

- Corpus `OpenSubtitles`, version **`v2024`**, language `en`, preprocessing **`raw`**
  (untokenized text, `<s id="...">` and `<time>` tags). The `xml`/parsed format splits text
  into `<w>` tags — useless here. The index knows seven releases (`v1`, `v2011`, `v2012`,
  `v2013`, `v2016`, `v2018`, `v2024`); `v2024` is the most recent and most complete.
- **The zip archive is never extracted.** It *is* the corpus: subtitles are read member by
  member via [corpus/archive.py](src/glyphwell/corpus/archive.py). This avoids tens of GB
  and hundreds of thousands of inodes, and keeps the corpus a single artifact verifiable by
  one checksum. Two consequences to know about: `zipfile` loads the whole central directory
  at open time (~150 MB for 400,000 members), and concurrent reads on the same handle
  serialize — **one handle per thread**.
- Internal layout, **prefix included**:
  `<corpus>/<preprocessing>/<language>/<year>/<imdb_id>/<opensubtitles_file_id>.xml`, e.g.
  `OpenSubtitles/raw/fr/2022/1596342/1957893755.xml`. The IMDb id there is **bare**
  (`1596342` → `tt1596342`). The last segment is the subtitle's id **on
  opensubtitles.org**, not an OPUS id: it identifies one specific translation, whereas
  `ImdbId` identifies the work. Don't conflate the two — that's the reason for the distinct
  aliases in [types.py](src/glyphwell/types.py).
- Subtitle members are plain `.xml` files: the zip is the only layer of compression.
  `corpus fetch` counts members with an unexpected suffix and reports them instead of
  coding defensively against a hypothetical case. The `INFO`, `README`, `LICENSE` service
  files at the archive root are counted separately, without raising an alarm.
- The `id` attribute of `<s>` tags is the resume key. It's ordered but not necessarily
  contiguous or purely numeric — treat it as an opaque ordinal.
- OPUS XML files aren't always well-formed: use `lxml` with `recover=True`.

#### `opustools` and OPUS API pitfalls

All verified against `opustools` 1.8.3 and the live index. Do not reintroduce them.

- **The stub was wrong.** The real signature is `OpusGet(source, target, directory,
  release, preprocess, list_resources, list_languages, list_corpora, download_dir,
  local_db, suppress_prompts, database)`: `directory` is the *corpus name*, `source` the
  *language*. `get_corpora_data()` takes no argument and returns a size **formatted as a
  string**. Never rewrite [the stub](stubs/opustools/__init__.pyi) from memory.
- **`OpusGet.get_files()` never fails**: it swallows `urllib.error.URLError` down to a
  `print`, has no timeout, can't resume, and writes straight to the final filename. A cutoff
  at 90% would leave a truncated archive indistinguishable from a complete one. Hence the
  transfer goes through `httpx` into a `.part` file resumed via a `Range` header, renamed
  only once complete.
- **The "single space" wildcard doesn't work live.** `OpusGet`'s code suggests that
  `release=" "` emits `version=` and means "all versions"; the live API then returns zero
  results. The parameter must be **omitted** instead (an empty string, which `OpusGet`
  doesn't emit).
- **In `raw` preprocessing, the index returns the monolingual archive of *every* language
  paired** with the one requested. Filtering on `target == ""` isn't enough: without
  `source == language`, an `en` request returns some fifty candidates (`eo`, `es`,
  `en_ze`...) and whichever one comes first would get downloaded.
- `OpusGet.url` ends with `&`, which its own code strips off when called.
- `make_file_name()` replaces the version with `latest` in the filename when
  `release == "latest"`: build the instance with the record's **concrete** version instead.
- The index's `size` field is in **kilobytes** and rounded (see `format_size`).

### Official IMDb datasets (sole metadata source)

IMDb is the project's **only** source of titles, and that's a deliberate choice: the id
carried by the OPUS corpus tree is an IMDb `tconst`, so the join is direct. Don't
reintroduce a third-party source (TMDB or otherwise): they're indexed by their own id, not
by `tconst`, which would force an approximate title-and-year match for information the
IMDb datasets already give exactly.

- `https://datasets.imdbws.com/title.basics.tsv.gz` gives `tconst`, `titleType`,
  `primaryTitle`, `originalTitle`, `isAdult`, `startYear`, `endYear`, `runtimeMinutes`,
  `genres`.
- `https://datasets.imdbws.com/title.episode.tsv.gz` gives `tconst`, `parentTconst`,
  `seasonNumber`, `episodeNumber`.
- TSV, **`\N` = null value** (not an empty string). Direct join on `tconst`,
  100% offline, no API key. Refreshed daily by IMDb.

What the IMDb datasets don't give: any popularity measure. If a filter like that becomes
necessary, the IMDb-native route is `title.ratings.tsv.gz` (`averageRating`, `numVotes`),
also indexed by `tconst` — not a third-party source.

### Volume

The English `v2024` / `raw` archive: **35.8 GB** (13.7 GB for `v2018`), several hundred
thousand members. It is not extracted: plan for its size, not double that.
`GLYPHWELL_DATA_DIR` must point to a disk with enough room. `data/` is gitignored and
fully reconstructible.

## 6. Resume invariants

This is the core of the program's correctness. Any change to
[search/](src/glyphwell/search/) must preserve these.

1. **Grain = the chunk.** A subtitle is split into sliding chunks of `chunk.size`
   sentences with `chunk.overlap` overlapping. One LLM call per chunk.
2. **`run_files.last_sentence_id` is the resume point.** It holds the id of the last
   sentence actually covered by a chunk whose result has been committed.
3. **One transaction per chunk**, which writes *both* the result and the cursor's
   progress. A crash can therefore neither lose a result nor advance the cursor
   incorrectly.
4. **Idempotence** via `UNIQUE(run_id, file_id, chunk_index)` on `results` plus
   `INSERT OR IGNORE`: replaying a chunk duplicates nothing.
5. **Deterministic queue order** (`ORDER BY rel_path`) in
   [search/planner.py](src/glyphwell/search/planner.py): a resume walks the same sequence
   again, so `chunk_index` always designates the same chunk.
6. **Freshness = `(opus_version, sha256)`.** `corpus refresh` recomputes the sha256; if it
   differs, only the `results` for **that** file are deleted and its `run_files` row goes
   back to `pending` with `last_sentence_id = NULL`. The rest of the run is kept.
7. **The manifest hash identifies the search.** Editing the YAML changes
   `runs.manifest_hash`: this creates a new run instead of mixing results produced by two
   different prompts. The YAML is archived in `runs.manifest_snapshot`.
8. **Clean shutdown.** A SIGINT finishes the current chunk, commits, and marks the run
   `paused` — it never leaves a file `in_progress` without a consistent cursor.

## 7. Data model

SQLite, **without FTS5**: subtitle text is neither copied nor indexed in the database —
only the catalog and progress state live there. Schema declared in
[db/schema.sql](src/glyphwell/db/schema.sql), version tracked via `PRAGMA user_version`.

| Table | Role |
|---|---|
| `titles` | IMDb titles: type, title, year, episode-to-series link. |
| `subtitle_files` | One archive member: member name, imdb_id, sha256, OPUS version. |
| `runs` | One search run: manifest, its hash, its snapshot, model, status. |
| `run_files` | Work queue and per-file **resume point** (`last_sentence_id`). |
| `results` | One model response per chunk, with its sentence range. |
| `corpus_downloads` | Traceability of OPUS downloads. |
| `imports` | Traceability of IMDb dataset imports. |

## 8. Current scope

The skeleton is in place, and **step 1 is operational**.

**Operational**: packaging, configuration, logging, SQLite schema and migrations
(`db init` produces a valid database), full CLI wiring, YAML manifest loading + validation
+ hashing, sha256 computation, and above all `glyphwell corpus fetch` — resolution against
the OPUS index ([corpus/opus.py](src/glyphwell/corpus/opus.py)), resumable download,
archive reading without extraction
([corpus/archive.py](src/glyphwell/corpus/archive.py)), traceability in `corpus_downloads`
(`CorpusDownloadsRepository`, the only repository implemented so far).

**Typed stubs** (`raise NotImplementedError`, signatures already complete and passing
strict mypy) — entry points for what comes next:

| Module | To implement |
|---|---|
| [corpus/layout.py](src/glyphwell/corpus/layout.py) | parsing the member name, normalizing the imdb_id |
| [corpus/reader.py](src/glyphwell/corpus/reader.py) | streaming XML reading into `Sentence` |
| [corpus/chunker.py](src/glyphwell/corpus/chunker.py) | sliding size/overlap chunking |
| [metadata/imdb_datasets.py](src/glyphwell/metadata/imdb_datasets.py) | download + TSV import |
| [metadata/resolver.py](src/glyphwell/metadata/resolver.py) | imdb_id to `Title` |
| [ollama/client.py](src/glyphwell/ollama/client.py) | model call, retries, JSON output |
| [ollama/prompts.py](src/glyphwell/ollama/prompts.py) | rendering the manifest's templates |
| [search/planner.py](src/glyphwell/search/planner.py) | building the work queue |
| [search/engine.py](src/glyphwell/search/engine.py) | loop, concurrency, clean shutdown |
| [search/checkpoint.py](src/glyphwell/search/checkpoint.py) | reading/writing the cursor |
| [search/results.py](src/glyphwell/search/results.py) | output validation, export |
| [db/repositories.py](src/glyphwell/db/repositories.py) | typed access to the tables, other than `corpus_downloads` |

Suggested order of attack: `corpus/layout.py`, `corpus/reader.py`, and `corpus/chunker.py`
(pure functions, testable without network access), then `db/repositories.py`, then
`metadata/imdb_datasets.py`, and finally `search/` together with `ollama/`.

Two decisions from step 1 constrain what comes next:

- `parse_entry` must **absorb the `<corpus>/<preprocessing>/` prefix** of the member name.
- `subtitle_files.rel_path` stores the **full member name**, prefix included: it's the only
  key that allows `CorpusArchive.open_member()` to work. `iter_corpus` now takes a
  `CorpusArchive`, not a directory root.
- `corpus/reader.py` will read a stream (`IO[bytes]`) coming from the archive, not a
  `Path`.
