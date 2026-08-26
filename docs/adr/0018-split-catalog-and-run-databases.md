# ADR-0018: Split the catalog and per-search run databases

**Status**: Accepted
**Date**: 2026-08-26

## Context

`glyphwell.db` held seven tables in one SQLite file: four fetched from the internet and
never mutated by a search (`titles`, `subtitle_files`, `corpus_downloads`, `imports`) and
three that only exist because a search was launched (`runs`, `run_files`, `results`).
`run_files.file_id` and `results.file_id` carried a live `FOREIGN KEY ... REFERENCES
subtitle_files(file_id) ON DELETE CASCADE`, enforced live (`PRAGMA foreign_keys = ON`,
`db/connection.py`).

This coupling has a real cost. Once the corpus is downloaded and cataloged
(`corpus fetch` + `corpus index`) and the IMDb datasets are imported
(`metadata fetch-imdb` + `import-imdb`), that data is immutable for the rest of the
project's life — a new subtitle arrives as a new row, never mutates an existing one (see
ADR-0015). Every search launched afterward, by contrast, produces its own progress state
that has nothing to do with any other search. Sharing one file forces every search to
read and write against the same growing catalog file, makes the catalog impossible to
back up, copy, or share independently of in-flight search state, and means a single
`glyphwell.db` accumulates the `runs`/`run_files`/`results` history of every search ever
launched, with no natural place to discard or archive one search's state without
touching the others'.

`glyphwell.search.planner.iter_work` — the hot path used by every real run and resume —
also relied on this being one file: it issued a single SQL statement joining `run_files`
to `subtitle_files` to get `ORDER BY sf.rel_path`, the deterministic traversal order
resume invariant §5 depends on (CLAUDE.md §7).

## Decision Drivers

- Catalog data (titles, subtitle files, download/import traceability) is immutable once
  fetched and should be a single, stable, shareable artifact, independent of any one
  search's lifecycle.
- Deterministic `ORDER BY rel_path` traversal (resume invariant §5) must survive the
  split without a per-row cross-database lookup at corpus scale (hundreds of thousands of
  files).
- Nothing has shipped yet (`CHANGELOG.md`: "Nothing has been released yet"), so this is a
  clean schema redesign, not a migration of live data.

## Considered Options

### Option 1: `ATTACH DATABASE`, keep the cross-database join

- **Pros**: `planner.iter_work`'s single-statement join survives almost unchanged, just
  qualified with an attached-schema alias.
- **Cons**: SQLite does not enforce `FOREIGN KEY` constraints across attached databases
  either — attaching buys back the join's convenience, not the integrity the FK used to
  provide, so the same trade-off (soft references) is paid either way. It also entangles
  the two files' connection lifecycles: a `search run` process would need to keep the
  catalog database attached for the run database's entire lifetime, which is the opposite
  of the independence the split exists for — a run database is meant to be a disposable,
  self-contained artifact that a user could `sqlite3`-inspect or delete without any
  reference to which catalog produced it.

### Option 2: Independent connections, `rel_path` duplicated into `run_files`

- **Pros**: `db/connection.py`'s existing one-`Path`-per-connection design needs no
  change; the two files' lifecycles are fully independent from the moment a search is
  created. Duplicating `subtitle_files.rel_path` into `run_files` at enqueue time
  (immutable per `file_id`, per ADR-0015 — a changed subtitle gets a new `file_id`, never
  mutates an existing row) lets `iter_work` become a plain, join-free, `ORDER BY rel_path`
  query over `run_files` alone, preserving invariant §5 exactly, at the cost of one
  duplicated `TEXT` column.
- **Cons**: `run_files.file_id`/`results.file_id` become soft, undeclared references —
  SQLite can no longer cascade-delete `run_files`/`results` rows if their `subtitle_files`
  row disappears from the catalog.

## Decision

Split into two databases, using **independent connections with no `ATTACH`** (Option 2):

- **Catalog database** (`schema_catalog.sql`): `titles`, `subtitle_files`,
  `corpus_downloads`, `imports`. Default name unchanged, `glyphwell.db`; path configurable
  via `--catalog-database` / `GLYPHWELL_CATALOG_DATABASE` (renamed from the previous
  `--database` / `GLYPHWELL_DATABASE`, now that "the database" is ambiguous between two
  kinds).
- **Run database** (`schema_run.sql`): `runs`, `run_files`, `results`. One per search,
  default name `<data_dir>/<manifest filename stem>.db`; path configurable via
  `--run-database` / `GLYPHWELL_RUN_DATABASE` on `search run`. Created and upgraded by
  `search run` itself (`initialize_run`, idempotent) — there is no separate `db init` step
  for a run database, unlike the catalog's.
- `run_files.file_id`/`results.file_id` drop their `FOREIGN KEY` declaration and become
  plain, undeclared references to the catalog database's `subtitle_files.file_id`.
- `run_files` gains a `rel_path` column, a copy of the catalog's `subtitle_files.rel_path`
  taken once at enqueue time (`planner.enqueue`), so `iter_work`'s `ORDER BY rel_path`
  never needs a join back to the catalog.
- Both schemas get their own independent `PRAGMA user_version` history, both starting
  fresh at version 1 (`CATALOG_SCHEMA_VERSION`, `RUN_SCHEMA_VERSION` in
  `db/migrations.py`) — there is no prior shipped version to carry forward.
- `search resume` / `search status` / `search export` take the run-database file path
  directly instead of a numeric `run_id`: a bare integer can no longer identify a search
  once `run_id` is only unique within its own file. The run database's `runs.
  manifest_snapshot` (a full copy of the YAML, already written at launch) makes the file
  itself the complete, durable handle for a search — consistent with `search resume`'s own
  pre-existing design of re-reading the manifest from that snapshot, never from disk.
- **Catalog storage-format cleanup, landed in the same change.** `titles.imdb_id`/
  `.parent_imdb_id` and `subtitle_files.imdb_id`/`.opensubtitles_file_id` are stored as
  `INTEGER` (`tt` stripped) instead of `TEXT`, converted at the `db/repositories.py`
  boundary via new `corpus/layout.py::imdb_id_to_int`/`imdb_id_from_int` — every other
  layer keeps the canonical `tt#######` string form, **except** the manifest's
  `select.imdb_ids`, which is now `tuple[int, ...]` (`imdb_ids: [133093]`, not
  `["tt0133093"]`) so it matches the column's storage type directly and needs no
  conversion in `search/planner.py::_select_clauses`. `corpus_downloads.downloaded_at`/
  `.verified_at` and `imports.imported_at` are typed `datetime.datetime` in their row
  dataclasses instead of `str` (storage stays `TEXT`: `STRICT` tables reject a literal
  `DATETIME` column type). `subtitle_files.discovered_at`/`.updated_at` and
  `titles.is_adult`/`.runtime_minutes`/`.source`/`.imported_at` are dropped — none were
  ever read back by any repository method, CLI command, or filter.

## Rationale

`ATTACH` was ruled out because it does not actually buy back what the split gives up: SQLite
never enforces foreign keys across attached databases, so the FK-across-files problem exists
identically whether or not the two files are attached together at query time. Since the
integrity trade-off is unavoidable either way, the deciding factor became which option better
serves the stated goal — an independent, shareable catalog — and independent connections win
that comparison directly, while `ATTACH` would have re-coupled the two files' lifecycles right
after the whole point of separating them.

Duplicating `rel_path` was checked against every current consumer of `PlannedFile`
(`search/engine.py::_process_queue`/`_admit`): none reads anything from a planned file besides
`file_id` — `rel_path`, the title, and the checkpoint are all independently re-fetched by
`_open_file` once a file is actually opened. This means the join elimination costs nothing in
practice: no code path needed the extra fields `PlannedFile` used to carry
(`imdb_id`, `sentence_count`), which are dropped along with the join.

The manifest's `select.imdb_ids` becoming numeric is the one deliberately user-facing piece
of the storage cleanup: everywhere else, the int/string boundary stays internal (a manifest
author never sees `titles`/`subtitle_files`' storage type). Keeping `imdb_ids` as the
canonical `"tt0133093"` string would have meant converting it back to int on every
`search/planner.py::_select_clauses` call for no benefit — the manifest is the one place a
human actually types the value, and the numeric form is what `subtitle_files.imdb_id` is
compared against directly, so leaving it numeric there removes a conversion instead of
hiding one.

## Consequences

### Positive

- The catalog database is a stable, single artifact that can be backed up, copied, or
  shared across many searches without any reference to which searches have run against it.
- Run databases are cheap and disposable: deleting one discards exactly one search's state,
  with no risk to the catalog or to any other search.
- `iter_work` and `RunFilesRepository.iter_pending` both simplify from a cross-table join to
  a single-table, index-backed query.

### Negative

- No database-enforced referential integrity between `run_files`/`results.file_id` and the
  catalog's `subtitle_files.file_id` — a row deleted or re-cataloged on the catalog side no
  longer cascades. Partially mitigated already: `search/engine.py::_open_file` already
  handles a file that "vanished from the catalog" as a per-file skip, not a crash, since
  nothing in the code ever deletes a `subtitle_files` row today.
- `search status`'s "no argument = list everything" meaning is now scoped to one run
  database's file, not every search ever launched — there is no cross-file registry of run
  databases. A future `glyphwell search list` globbing `data_dir/*.db` is a natural
  follow-up, out of scope here.
- `db status`/`db vacuum` operate on the catalog database only; a run database's own
  maintenance (e.g. `VACUUM` after heavy `results` churn) has no dedicated command yet — a
  plain `sqlite3 <run>.db VACUUM` works as a stopgap.
- A manifest written against the previous string-form `select.imdb_ids` (`["tt0133093"]`)
  no longer validates — pydantic rejects a non-integer element outright, rather than
  silently misinterpreting it. Acceptable only because nothing has shipped yet; a real
  release would need this called out as a breaking manifest-format change.

### Risks

- If a future feature needs to join catalog and run data in one query at scale (beyond the
  per-file lookups `_open_file` already does), revisit this decision — the soft-reference
  trade-off accepted here would need to be paid again, or `ATTACH` reconsidered for that one
  read path specifically.

## Related

- ADR-0002 (SQLite for the catalog and run state, no FTS5 — this ADR splits what ADR-0002
  originally treated as one database).
- ADR-0005 (resume invariants, including deterministic queue order, that this split
  preserves).
- ADR-0012 (thread-confined SQLite connections — unaffected: both `catalog_conn` and
  `run_conn` stay owned by the same thread).
- ADR-0015 (why duplicating `rel_path` into `run_files` is safe: a `file_id` is immutable
  once assigned).
- ADR-0017 (the eager work-queue materialization this split's `iter_work` rewrite
  preserves unchanged).
- `db/schema_catalog.sql`, `db/schema_run.sql`, `db/migrations.py`, `search/planner.py`,
  `search/engine.py`, `cli/search.py`.
- `corpus/layout.py::imdb_id_to_int`/`imdb_id_from_int`, `manifest/model.py::SelectConfig`
  (the storage-format cleanup landed alongside the split).
