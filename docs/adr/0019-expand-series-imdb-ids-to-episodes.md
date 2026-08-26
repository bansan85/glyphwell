# ADR-0019: Expand a series id in `select.imdb_ids` to its episodes

**Status**: Accepted
**Date**: 2026-08-26

## Context

`subtitle_files.imdb_id` stores an episode's own IMDb id, never its series' — OPUS's
TV-episode compound segment (`<episode_id>_<series_id>_<season>_<episode>`) is parsed
down to just the episode id (ADR-0016), and only `titles.parent_imdb_id` (filled in from
`title.episode.tsv`) records which series an episode belongs to. `manifest/model.py`'s
`SelectConfig.imdb_ids` lets a manifest restrict a search to an explicit set of titles,
and until now `search/planner.py::_matching_page_query` filtered with
`sf.imdb_id IN (...)` alone. Listing a series' id in `imdb_ids` — the natural way to say
"search everything in this show" — therefore matched zero files: no `subtitle_files` row
ever carries a series' own id.

Fixing this means joining the filter against `titles.parent_imdb_id`. `db/schema_catalog.sql`
deliberately carries no index on that column: ADR-0011 measured that maintaining
`idx_titles_parent` during the IMDb bulk import roughly halved throughput, and dropped it
because nothing in the codebase queried `titles` by `parent_imdb_id` at the time. ADR-0011
named this exact feature ("series -> episodes") as the concrete case that would need the
index back, and CLAUDE.md §6 repeats the same warning almost verbatim. Since then, though,
`SelectConfig.title_types`/`years` shipped against the sibling `idx_titles_type_year` index
without it being re-added — that decision was deferred instead of assumed, and recorded as
a "Known limitation" in `CHANGELOG.md` pending an `EXPLAIN QUERY PLAN` measurement.

## Decision Drivers

- A series id in `imdb_ids` must actually select its episodes; matching nothing silently
  is worse than the field simply not existing.
- `import-imdb`'s bulk-import throughput (the regression ADR-0011 measured and removed)
  must not regress again for a query pattern not yet shown to need the index it was paid
  for.
- `--dry-run` (`cli/search.py::_matches_select`) and a real run's queue
  (`search/planner.py::_matching_page_query`) must agree on which files match — a preview
  that disagrees with what a real run would enqueue is worse than no preview.
- A fresh `db init` and an upgraded database must keep producing the same schema
  (`db/migrations.py`), which constrains *how* any index is reintroduced, not whether one
  is needed right now.

## Considered Options

### Option 1: Re-add `idx_titles_parent` via a new migration, alongside the query change

- **Pros**: matches ADR-0011's own anticipated follow-up to the letter; guarantees the
  join never falls back to a full scan of `titles`, whatever the query planner would
  otherwise pick.
- **Cons**: pays back the exact bulk-import throughput regression ADR-0011 measured and
  removed, for a query pattern not yet shown to need it. `_matching_page_query` still
  drives its scan off `subtitle_files` (keyset-paginated on `sf.file_id`) and reaches the
  joined `titles` row by primary key — a plan an index on `parent_imdb_id` cannot speed
  up, since the join never seeks into `titles` by that column. Adding the index here would
  pay a real, measured cost against a hypothetical one.

### Option 2: Filter on `sf.imdb_id OR t.parent_imdb_id`, no index, measure first (chosen)

- **Pros**: the fix is exactly as large as the bug — one `OR` branch in
  `_select_clauses` (and its mirror in `_matches_select`) — with no schema change, no
  migration, and no risk to import throughput. Consistent with the precedent already set
  for `title_types`/`years`: implement, measure, add the index only if
  `EXPLAIN QUERY PLAN` on a populated database shows it matters.
- **Cons**: leaves open the possibility that a future query shape (one that scans
  `titles` first and reaches `subtitle_files` from there, rather than the other way
  around) would want the index after all; that measurement has not been done.

### Option 3: Resolve the series' episodes in Python before building the query

Look up every `titles` row whose `parent_imdb_id` matches a requested series id first
(one query per series, or a batched one), then fold the resulting episode ids into the
existing `sf.imdb_id IN (...)` list.

- **Pros**: keeps `_matching_page_query`'s `WHERE` clause shape unchanged.
- **Cons**: the same missing-index problem, just moved one step earlier — that lookup is
  itself a `parent_imdb_id` scan, only now outside the paginated query. Doesn't compose
  with `_unresolved_query`'s existing left-join/unresolved-count logic, and adds a second
  read path that the dry-run preview would also need to duplicate to stay in sync.

## Decision

Filter on `(sf.imdb_id IN (...) OR t.parent_imdb_id IN (...))` in
`search/planner.py::_select_clauses`, reused by both `_matching_page_query` (inner join)
and `_unresolved_query` (left join, where an unresolved file's `t` columns are `NULL` and
only the direct-id branch can still match). `cli/search.py::_matches_select` mirrors the
same rule against `Title.parent_imdb_id` for `--dry-run`. No migration, no index, in this
change.

## Rationale

Option 1 optimizes a query plan that was never shown to need it, at a cost ADR-0011
already measured and rejected once — reintroducing it here would repeat that mistake for
the same unproven reason ADR-0011 flagged as the trigger, without first checking whether
the trigger actually applies to this query's shape. Option 3 relocates the same missing
index one join earlier without removing the need for it, while giving up shared
unresolved-file handling and creating a second place for the dry-run preview to drift out
of sync with the real query. Option 2 is the smallest change that fixes the actual
defect (a series id matching nothing) and defers the schema question to exactly where the
codebase already put it for the sibling `title_types`/`years` case: behind a real
measurement, not a preemptive one.

## Consequences

### Positive

- `select.imdb_ids` naming a series now does what a manifest author would expect: every
  episode of that series is selected, with no change to `db/schema_catalog.sql` or
  `db/migrations.py`.
- `import-imdb`'s bulk-import throughput is unaffected — nothing added to the write path.
- `--dry-run` and a real run's queue stay in agreement on which files match.

### Negative

- `_matching_page_query`'s `titles` join now serves two independent lookup directions
  (`imdb_id` primary-key equality for the direct-id branch, `parent_imdb_id` for the
  series branch) with only the primary key backing either efficiently; the
  `parent_imdb_id` branch is a per-row filter evaluated after the join, not a seek.

### Risks

- If a future change alters how `_matching_page_query` drives its scan (for example,
  filtering by `title_type`/`start_year` first and reaching `subtitle_files` from
  `titles` instead of the other way around), the `parent_imdb_id` branch could become the
  query's dominant cost. Measure with `EXPLAIN QUERY PLAN` on a populated database before
  assuming either way, and add `idx_titles_parent` back via a new migration — not by
  uncommenting the dropped `CREATE INDEX` in `schema_catalog.sql` — if it turns out to
  matter. Same posture `CHANGELOG.md`'s "Known limitations" already documents for
  `idx_titles_type_year`.

## Related

- ADR-0011 — drop the secondary indexes on `titles` (named this exact "series ->
  episodes" query as its anticipated follow-up; this ADR is that follow-up, choosing not
  to reinstate the index yet).
- ADR-0016 — keep only the episode id from the TV-episode compound segment (why
  `subtitle_files.imdb_id` never carries a series id in the first place).
- ADR-0018 — split the catalog and per-search run databases (the `titles`/
  `subtitle_files` join this decision extends lives entirely in the catalog database).
- `search/planner.py::_select_clauses`/`_matching_page_query`/`_unresolved_query`,
  `cli/search.py::_matches_select`, `manifest/model.py::SelectConfig.imdb_ids`.
- CLAUDE.md §6, "No secondary index on `titles`" — the standing warning this ADR
  responds to.
- CHANGELOG.md's "Known limitations" — the `SelectConfig.title_types`/`years` entry this
  decision mirrors, and the new entry backed by this ADR for `imdb_ids`.
