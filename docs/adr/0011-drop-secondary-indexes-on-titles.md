# ADR-0011: Drop the secondary indexes on `titles`

**Status**: Accepted
**Date**: 2026-08-25

## Context

`schema.sql` (version 1) declared two secondary indexes on `titles`, alongside the
primary key on `imdb_id`:

- `idx_titles_parent` on `parent_imdb_id` (partial, `WHERE parent_imdb_id IS NOT NULL`).
- `idx_titles_type_year` on `(title_type, start_year)`.

While testing a real `import-imdb` run against the full IMDb catalogue (title.basics
12.7M rows, title.episode 9.8M rows), throughput was observed to degrade progressively
as the import advanced — not a constant per-row cost, but one that visibly worsened over
time.

Profiling isolated the cause to these two indexes. Their keys do not correlate with
`title.basics.tsv`'s insertion order (rows arrive ordered by `tconst`, not by
`title_type`/`start_year`/`parent_imdb_id`), so every write lands on an effectively
random B-tree leaf instead of an appending one — a cost that grows as each index
outgrows the page cache. Measured on a 4M-row real slice, alternating 500k-row windows:

| | With both secondary indexes | Without them |
|---|---|---|
| Throughput | ~20,000–37,000 rows/s, irregular, with visible dips (e.g. one window at 20,232 rows/s) | ~50,000–61,000 rows/s, stable |

The only lookup direction the project actually performs today is `imdb_id -> title`
(`TitlesRepository.get`, `SqliteTitleProvider.resolve`), already served by the primary
key. Neither secondary index backs any query in the current codebase.

One caveat found while writing this ADR: `manifest/model.py`'s `SelectConfig` already
declares `title_types` and `years` (a `YearRange`) as manifest fields — a prefilter this
project intends to support once `search/planner.py` is implemented (it currently raises
`NotImplementedError`). That filter, when written, is exactly the query
`idx_titles_type_year` was shaped for. It does not exist yet, so it is not a reason to
keep an index paying for it today, but it is the concrete "future feature" this decision
defers.

## Decision Drivers

- Bulk-import throughput of the full IMDb catalogue must not degrade as the table grows.
- Only the `imdb_id -> title` lookup direction needs to stay fast; nothing in the
  codebase queries `titles` by `parent_imdb_id` or `(title_type, start_year)` today.
- A schema change must apply the same way to a fresh `db init` and to an
  already-initialized database (see `db/migrations.py`).

## Considered Options

### Option 1: Leave the indexes as they are

- **Pros**: no change.
- **Cons**: the measured throughput regression (roughly halved, and worsening as the
  table grows) is paid on every full import, for two query directions nothing performs.

### Option 2: Drop before the bulk import, rebuild once after

Drop `idx_titles_parent`/`idx_titles_type_year` at the start of `import-imdb`, run
`import_basics` and `import_episodes`, then recreate both indexes in a single
`CREATE INDEX` pass (cheaper than incremental maintenance, since SQLite can build an
index from a sorted scan in one go).

- **Pros**: keeps both lookup directions available for whatever queries the table
  serves, while still avoiding the incremental-maintenance cost during the bulk write.
- **Cons**: extra state to manage (an interrupted import could leave the indexes
  dropped until the next full run); the rebuilt indexes still serve no query today, so
  the complexity buys nothing currently in use; two knobs (`drop_*`/`rebuild_*`) to keep
  in sync with `schema.sql` and with each other.

### Option 3: Drop the indexes permanently (chosen)

Remove both `CREATE INDEX` statements from `schema.sql`, and add a `db/migrations.py`
version-2 migration that drops them on an existing (version 1) database.

- **Pros**: no per-import bookkeeping; the schema directly reflects the one lookup
  direction the project performs; faster by default, always, not just during a bulk
  import.
- **Cons**: the title/year -> imdb_id and series -> episodes lookup directions are gone
  until a future migration reintroduces the relevant index.

## Decision

Drop `idx_titles_parent` and `idx_titles_type_year` from `schema.sql`, and add them to
`db/migrations.py`'s version-2 migration as `DROP INDEX IF EXISTS` statements so an
existing database is brought in line. `SCHEMA_VERSION` becomes `2`.

## Rationale

Option 3 matches the actual, current shape of the problem: this project only ever reads
`titles` by `imdb_id`. Option 2's added complexity (drop/rebuild orchestration, a window
where the database has fewer indexes than its declared schema) would only be justified
by a query pattern that does not exist in the codebase yet. If `search/planner.py`
later implements `SelectConfig.title_types`/`years` filtering against `titles`, the
right move is a new migration that adds back a purpose-built index — not resurrecting
this one from a comment, since a fresh `db init` and an upgraded database must keep
producing the same schema (see `schema.sql`'s comment at the removal site).

## Consequences

### Positive

- Full-catalogue import throughput roughly doubles and stops degrading as the table
  grows (measured: ~20,000–37,000 rows/s -> ~50,000–61,000 rows/s on a 4M-row slice).
- No per-import index bookkeeping; `import_basics`/`import_episodes` are unaware indexes
  were ever a concern.
- The schema honestly reflects the single lookup direction in use.

### Negative

- `SELECT * FROM titles WHERE parent_imdb_id = ?` (series -> its episodes) and
  `SELECT * FROM titles WHERE title_type = ? AND start_year BETWEEN ? AND ?` now require
  a full table scan (~12.7M rows). Nothing in the codebase issues either query today.

### Risks

- **`SelectConfig.title_types`/`years` (`manifest/model.py`) will need this lookup back
  once `search/planner.py` is implemented.** It is declared in the manifest schema
  already but not yet consumed by any query — `search/` still raises
  `NotImplementedError` end to end. Whoever implements that prefilter should re-add a
  purpose-built index (a new migration, matching whatever the actual query shape turns
  out to be) rather than assume `idx_titles_type_year` still exists.

## Related

- `glyphwell.db.repositories.TitlesRepository.get`, `.upsert_many`,
  `.set_episode_links_many`.
- `db/schema.sql` (the comment at the removal site), `db/migrations.py` version 2.
- `glyphwell.manifest.model.SelectConfig` (`title_types`, `years`) — the deferred
  consumer of the dropped `idx_titles_type_year`.
- ADR-0003 — use the official IMDb datasets as the sole metadata source.
- ADR-0010 — two-pass IMDb import (the other `titles`-shaping decision from the same
  work).
- CLAUDE.md §6, "No secondary index on `titles`".
