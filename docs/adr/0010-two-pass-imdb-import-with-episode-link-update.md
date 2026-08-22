# ADR-0010: Two-pass IMDb import — coalescing upsert plus a dedicated episode-link update

**Status**: Accepted
**Date**: 2026-08-22

## Context

`title.basics.tsv` and `title.episode.tsv` (ADR-0003) are imported independently, in that
order, into the single `titles` table. Neither file carries the full row on its own:

- `import_basics` never knows an episode's parent series, season, or episode number —
  that information only exists in `title.episode.tsv`.
- `import_episodes` never knows the rest of a title's columns, including `is_adult`,
  which is `NOT NULL` in the schema.

Both imports must also be safely re-runnable: `fetch-imdb` can be re-run to pick up a
fresher daily export, and re-running `import-imdb` on the same or a refreshed file must
not require any manual cleanup first.

## Decision Drivers

- Re-running `import_basics` (e.g. after a fresh download) must not erase the
  episode-to-series link written by a previous `import_episodes`.
- `import_episodes` must not have to invent a value for a column it has no data for,
  particularly the non-nullable `is_adult`.
- Each pass should write with a single statement per row, not a read before every write.

## Considered Options

### Option 1: One coalescing upsert used by both passes

`TitlesRepository.upsert_many(rows: Sequence[TitleRow])` already coalesces every
nullable column against what is already stored, so a value the caller doesn't have
(`None`) never overwrites one already on the row. Using the same method for
`import_episodes` would mean building a `TitleRow` with only `imdb_id`,
`parent_imdb_id`, `season_number`, and `episode_number` filled in.

- **Pros**: one write path, no new repository method.
- **Cons**: `TitleRow.is_adult` is a plain `bool`, not `bool | None` — there is no way to
  express "unknown" for it. An episode-only `TitleRow` would have to supply a concrete
  `False`, and coalescing does not help: `False` is not `NULL`, so it would silently
  overwrite a `True` written by `import_basics`.

### Option 2: Read-modify-write before every episode row

Fetch the existing `TitleRow` for the episode's `imdb_id`, merge in the season/episode/
parent fields, and write the merged row back through `upsert_many`.

- **Pros**: keeps a single write method; every column stays correct by construction.
- **Cons**: doubles the I/O of `import_episodes` — an extra `SELECT` for each of
  `title.episode.tsv`'s several million rows — for information (`is_adult`,
  `title_type`, …) that is simply not touched by this pass. Also a lot of code — build a
  full row just to change three columns of it — for what is otherwise a target-friendly
  bulk update.

### Option 3: A dedicated, narrower write for the episode link (chosen)

Add `EpisodeLink` (`imdb_id`, `parent_imdb_id`, `season_number`, `episode_number`) and
`TitlesRepository.set_episode_links_many(links: Sequence[EpisodeLink])`, a plain
`UPDATE … SET parent_imdb_id = ?, season_number = ?, episode_number = ? WHERE imdb_id =
?` — not an upsert. `import_basics` keeps using `upsert_many`; `import_episodes` uses
only `set_episode_links_many`.

- **Pros**: neither method ever has to guess a value it doesn't have. No extra read.
  `UPDATE` also expresses the real precondition directly: an episode's own row must
  already exist (from `import_basics`) for the link to attach.
- **Cons**: two write paths on the same table to keep in sync with future schema
  changes, instead of one.

## Decision

`TitlesRepository.upsert_many` is used only by `import_basics`; `import_episodes` uses
the dedicated `TitlesRepository.set_episode_links_many`, which only ever touches
`parent_imdb_id`, `season_number`, and `episode_number`.

## Rationale

Option 3 is the only one where neither pass can silently invent a value for a column it
doesn't have data for. It also matches the shape of the problem: `import_episodes` is
genuinely a narrower operation (attach a link to an existing row) than `import_basics`
(write or refresh a whole row), so it gets a narrower primitive instead of being forced
through the general-purpose one.

## Consequences

### Positive

- `import_basics` can be re-run at any time — a fresh daily `title.basics.tsv.gz` — 
  without disturbing links written by a previous `import_episodes`.
- `import_episodes` can equally be re-run without touching `is_adult`, `title_type`, or
  any other basics column.
- Both passes remain a single statement per row: no read-modify-write anywhere in the
  import path.

### Negative

- Two repository methods now write to `titles` instead of one, so a future column added
  to the table has to be reviewed against both.

### Risks

- **Run order is a real precondition, not just a suggestion.** `set_episode_links_many`
  is a plain `UPDATE`: if a given episode's `imdb_id` has never been written by
  `import_basics` (import not yet run, or the row filtered out for some future reason),
  the `UPDATE` matches zero rows and the link is silently dropped — not an error, just a
  no-op. `TitlesRepository.set_episode_links_many` returns the count of rows actually
  updated, so a caller that wants to detect this can compare it against the number of
  links attempted, but `import_episodes`/`import-imdb` do not currently do so; a partial
  link count is not surfaced anywhere today. Mitigated only by documentation (CLAUDE.md
  §6, `import_episodes`'s docstring, this ADR) and by CLI ordering
  (`import-imdb` always runs `import_basics` before `import_episodes`), not by a runtime
  check.

## Related

- `glyphwell.db.repositories.TitlesRepository.upsert_many` /
  `set_episode_links_many`, `EpisodeLink`.
- `glyphwell.metadata.imdb_datasets.import_basics` / `import_episodes`.
- ADR-0003 — use the official IMDb datasets as the sole metadata source.
- CLAUDE.md §6, "Two-pass import, not a single upsert".
