# ADR-0016: Keep only the episode id from the TV-episode compound segment

**Status**: Accepted
**Date**: 2026-08-25

## Context

`corpus/layout.py`'s documented archive layout is
`<corpus>/<preprocessing>/<language>/<year>/<imdb_id>/<opensubtitles_file_id>.xml`, with
`imdb_id` assumed bare (`1596342`). `normalize_imdb_id` enforced that with a strict
`^\d+$` check, so any other shape raised `CorpusLayoutError` and `iter_corpus` silently
skipped the member (logged at `debug`, one aggregate `warning` at the end of the scan).

Inspecting the actual downloaded archive (`data/corpus/OpenSubtitles_v2024_raw_en.zip`)
showed that assumption was wrong for TV episodes: that segment is instead
`<episode_imdb_id>_<series_imdb_id>_<season>_<episode>`, e.g. `674159_47763_2_13`. This
is not an edge case — **64.5%** of subtitle members in the real `v2024`/`raw`/`en` archive
(821,918 of 1,274,672) use this compound form, meaning `corpus index` was silently
dropping every TV episode, close to two thirds of the corpus.

A 200-item random sample of compound segments was cross-checked against
`title.episode.tsv`:

- The first field resolves to an actual `tvEpisode` row 198/200 times (99%).
- Among those, the embedded series id, season, and episode number matched
  `parentTconst`/`seasonNumber`/`episodeNumber` exactly in 195/198 (98.5%) — the other 3
  differed by a small season/episode offset.

So the three trailing fields are a scrape-time snapshot of facts the IMDb datasets already
carry, and one that can drift from IMDb's current values (IMDb data is refreshed daily and
user-edited; OPUS's copy is frozen at build time).

## Decision Drivers

- Every TV episode subtitle must become a catalogued `subtitle_files` row — the drop is
  the defect being fixed.
- Do not reintroduce a second source of truth for season/episode/parent-series data:
  ADR-0003 already made the IMDb datasets the sole metadata source, specifically to avoid
  reconciling two disagreeing catalogs.
- Keep `parse_entry`/`normalize_imdb_id` pure string parsing, with no database or import
  ordering dependency — `corpus index` and `metadata import-imdb` are independent today,
  and nothing currently requires one to precede the other.
- Minimize schema and API churn: nothing downstream of `CorpusEntry` currently needs
  season/episode at cataloging time — `metadata/resolver.py` already serves that once the
  episode's own `imdb_id` is known.

## Considered Options

### Option 1: Keep only the episode's own imdb_id, discard the rest

- **Pros**: Fits the existing single-`imdb_id` shape of `CorpusEntry` and
  `subtitle_files` exactly — no schema migration, no repository change, no changes
  outside `corpus/layout.py`. Episode-to-series/season/episode resolution already exists
  (`metadata/resolver.py` plus `title.episode.tsv`, imported daily) and is guaranteed
  fresher than a value frozen into the archive at OPUS build time. `parse_entry` stays a
  pure function.
- **Cons**: Throws away three fields already parsed for free; until `import-imdb` has
  been run, a TV episode's season/episode is not derivable from the catalog alone —
  though that dependency on the IMDb import already exists for every title lookup
  (ADR-0003), not just this one.

### Option 2: Parse and store the embedded series_id/season/episode as extra fields

- **Pros**: Season/episode context available immediately from the corpus tree, without
  needing `title.episode.tsv` imported first.
- **Cons**: Reintroduces a second, parallel source of truth for exactly the facts
  ADR-0003 assigned to the IMDb datasets alone — and the spot check shows that second
  source can be wrong 1.5% of the time. Requires a `subtitle_files` migration and new
  `CorpusEntry` fields for data that becomes redundant the moment `import-imdb` has run.

### Option 3: Cross-validate the embedded fields against `title.episode.tsv` at index time

- **Pros**: Would have caught the observed 1.5% drift as an explicit signal instead of a
  silently discarded fact.
- **Cons**: Forces `corpus/layout.py` — documented as pure path parsing over an archive
  that "designates no file on disk" — to depend on the database and on `import-imdb`
  having already run, an ordering constraint that does not exist today. The drift is
  otherwise inert: once the fields are discarded, nothing downstream ever reads them, so
  validating them buys a diagnostic with no consumer.

## Decision

Keep only the episode's own id (Option 1). `normalize_imdb_id` in
[corpus/layout.py](../../src/glyphwell/corpus/layout.py) recognizes the compound form via
a dedicated pattern (`_EPISODE_SEGMENT`, `^\d+_\d+_\d+_\d+$`) and, on a match, normalizes
only its first field; the series id, season, and episode number are parsed only far enough
to be recognized as the expected shape, then dropped. `CorpusEntry` and `subtitle_files`
are unchanged.

## Rationale

The compound segment carries two kinds of information: an id (the episode's own,
resolvable and authoritative) and a caption (series/season/episode, a snapshot that can
go stale). Once ADR-0003 fixed the IMDb datasets as the sole source for the caption, the
only thing this layer needs to extract is the id — anything else would be maintaining a
second, occasionally-wrong copy of data already owned elsewhere, exactly the situation
ADR-0003 exists to prevent.

## Consequences

### Positive

- `corpus index` now catalogs the full corpus. Re-running `iter_corpus` against the
  locally downloaded `v2024`/`raw`/`en` archive yields 1,274,671 of 1,274,672 `en`
  members, up from 452,753 before this change (the one remaining skip is an unrelated
  pre-existing path anomaly, unaffected by this decision).
- Zero schema or API churn: `CorpusEntry`, `subtitle_files`, and every consumer
  (`cli/corpus.py`, `cli/search.py`) are unchanged.
- Season/episode/parent-series context for a TV episode stays sourced exclusively from
  the IMDb datasets, never from a value baked into the archive at some past OPUS build.

### Negative

- The parsed `CorpusEntry` no longer exposes the segment's season/episode/series fields
  even though they were available for free; only the raw `rel_path` retains them, for
  anyone inspecting the corpus tree directly without a populated database.
- Resolving a TV episode's title/season/episode still requires `import-imdb` to have been
  run — an existing dependency (ADR-0003), not a new one, but one this decision does
  nothing to relax for the case where only the archive is available.

### Risks

- If a future OPUS release changes the compound form's field count or order,
  `_EPISODE_SEGMENT` simply fails to match and the segment falls through to the bare-digit
  check, which also fails — the member is skipped and counted, the same fail-closed
  behavior `iter_corpus` already relies on for any unrecognized shape, not a silent
  mis-parse.

## Related

- Builds on ADR-0003 (IMDb datasets as sole metadata source).
- `src/glyphwell/corpus/layout.py` (`normalize_imdb_id`, `_EPISODE_SEGMENT`),
  `tests/test_corpus_layout.py`.
