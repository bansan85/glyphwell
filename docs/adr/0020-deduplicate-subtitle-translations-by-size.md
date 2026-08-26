# ADR-0020: Deduplicate subtitle translations by size

**Status**: Accepted
**Date**: 2026-08-26

## Context

OpenSubtitles frequently carries several independent translations for the same title:
`OpenSubtitles/raw/en/1892/2/` alone holds 12 member files for one `imdb_id`. Measured on
the real `v2024`/`raw`/`en` archive (1,719,994 subtitle members, grouped by their
`(imdb_id)` directory): 444,711 distinct titles, of which **241,285 (54%) have two or more
candidate files**. Sending every one of them through Ollama multiplies a search's model-call
cost for no proportional gain in coverage, since a large share of that redundancy is
either near-duplicate uploads or degenerate variants: OpenSubtitles listings mix full
dialogue transcripts with forced-only (foreign-dialogue-only) subtitles,
SDH/closed-caption tracks (dialogue plus sound-effect and speaker annotations),
director's-commentary transcriptions, partial or wrongly-cut uploads, and outright
duplicates — none of which OPUS's `raw` preprocessing distinguishes: the archive layout
(`corpus/layout.py::parse_entry`) exposes only the member's path and, since this decision,
its uncompressed size; nothing about a subtitle's type, completeness, or quality survives
into it.

The goal is a `select` filter, on by default, that keeps one file per
`(imdb_id, language)` — the one most likely to carry the fullest, legitimate dialogue
transcript — without reading subtitle content: `corpus index` deliberately reads no member
content today (ADR-0015), and re-opening every candidate of every duplicate group to judge
it would undo that property for a filter meant to *reduce* cost, not add a new read pass
over a large fraction of the corpus.

An initial proposal — always keep the single largest file — was tested against three real
duplicate groups and against the full-archive size distribution before being refined
twice over the course of this decision; the percentiles below are what settled the two
thresholds actually shipped.

## Decision Drivers

- Must reduce Ollama calls without silently discarding the fullest legitimate transcript
  for a title — losing dialogue coverage defeats the search's purpose more than the extra
  model calls cost.
- Must rank candidates using only data already free at `corpus index` time (no member
  content read), preserving the property ADR-0015 established.
- Must produce a deterministic pick: the same catalog state must always yield the same
  winner, independent of database insertion order.
- Must not require rewriting `search/planner.py::enqueue`'s existing paginated,
  transactional write loop, already relied on for its WAL-checkpoint-safety properties.
- `--dry-run` and a real run must agree on which file a group's deduplication resolves to
  — the same driver ADR-0019 already established for `select.imdb_ids`'s series
  expansion: a preview that disagrees with what a real run would process is worse than no
  preview.

## Considered Options

### Option 1: Keep the single largest file (`MAX(size_bytes)`)

- **Pros**: trivial to compute (a single `ORDER BY size_bytes DESC LIMIT 1` per group, or
  an equivalent window function), zero extra parameters to calibrate.
- **Cons**: no defense against a file that is largest for the wrong reason — a
  concatenated multi-part release, a wrong (extended/theatrical) cut sharing the same
  `imdb_id`, or an upload padded with repeated/spam lines would win undeservedly. Measured
  on the real archive, the top-two-candidate size ratio has a long tail (p99.9 = ×28.5,
  max observed = ×189) that a plain maximum cannot distinguish from ordinary
  dialogue-vs-SDH variation.

### Option 2: Trimmed-mean "most typical size"

Drop the smallest and largest 20% of a group's candidates, average the remaining 60%, and
keep whichever real file is closest to that average.

- **Pros**: a recognized robust-statistics technique; immune to a single extreme outlier
  on either end.
- **Cons**: targets "the most *typical* file," not "the most *complete* legitimate one" —
  on the real 12-file group above, it selects a mid-range file (296,112 bytes) over the
  legitimate largest one (390,208 bytes, only ×1.04 above its runner-up — not an outlier by
  any measure), discarding content a full dialogue+SDH transcript would have added. The
  20%/80% split is also close to inert at the group sizes actually observed: trimming 20%
  of a 5-candidate group removes one element per side and converges on the plain median;
  most groups in the corpus are this small.

### Option 3: Purge low outliers, guard against a high outlier, keep the max (chosen)

Iteratively drop a group's smallest candidate while it sits below half the group's current
median (a forced-only/commentary-track signature), then iteratively drop the current
maximum while it exceeds twice its runner-up (a signature of a different cut, a
concatenated release, or similar), and return whatever remains largest.

- **Pros**: keeps Option 1's "maximize legitimate content" target instead of Option 2's
  "typical size" target, while adding exactly the two guardrails the real data shows are
  needed — evidence below.
- **Cons**: two thresholds to calibrate and justify, instead of zero (Option 1) or one
  (Option 2, itself poorly justified at the observed group sizes).

### Option 4: Rank by real sentence count instead of byte size

Open every candidate and use `corpus/reader.py::count_sentences` instead of
`size_bytes` — a cleaner proxy for dialogue length, insensitive to verbose lines.

- **Pros**: more directly measures what actually matters (how much dialogue a chunk-based
  search would see), not a byte-size proxy for it.
- **Cons**: requires opening and parsing every candidate of every duplicate group —
  real I/O and XML parsing across roughly half the corpus's titles, undoing the
  "`corpus index` reads no content" property (ADR-0015) for a filter whose entire purpose
  is cost reduction. `size_bytes` is already free at index time (the zip central
  directory); nothing in this decision showed the byte-size proxy to be unreliable enough
  to justify paying that cost.

## Decision

Rank a group's candidates by `size_bytes` alone (Option 3):
`search/dedup.py::select_representative` iteratively purges a candidate below
`_LOW_OUTLIER_RATIO = 0.5` of the group's current median, then — requiring at least 3
remaining candidates, since with only 2 there is no third point of reference to tell a
genuinely larger transcript from an outlier — iteratively purges a current maximum above
`_HIGH_OUTLIER_RATIO = 2.0` of its runner-up, and returns whichever candidate remains
largest. Ties are broken on the lowest `opensubtitles_file_id`, compared numerically (it
is stored as `str`; a lexicographic comparison would misorder ids of different digit
counts).

Both thresholds are calibrated against the real archive: measured across 241,285 duplicate
groups, the top-two-candidate size ratio sits at p50 = ×1.04, p95 = ×1.366, and only
crosses ×2.0 past p99 (2.286), continuing to p99.9 = ×28.5 and a maximum of ×189 — ×2.0
catches the long tail without ever touching ordinary dialogue-vs-SDH variation. The
smallest-candidate-to-median ratio sits at p50 = 0.956, p25 = 0.90, p10 = 0.79, then drops
sharply to p5 = 0.58 and p1 = 0.0275 — ×0.5 sits inside that gap.

`corpus index` now records each member's uncompressed size in `subtitle_files.size_bytes`
(`corpus/layout.py::CorpusEntry.size_bytes`, from `ArchiveMember.size` — the zip's central
directory, already read when the archive opens; no member content read, no change to
ADR-0015's guarantee). `search/planner.py::enqueue` computes the winners of every group
matching a search's `select` filters in one dedicated read-only pass
(`_prepare_dedup_winners`), stages them in a temp table, and adds
`sf.file_id IN (SELECT file_id FROM dedup_winners)` to the existing, unmodified
`_matching_page_query` pagination loop. The new manifest field
`SelectConfig.one_subtitle_per_title` (default `true`) controls it per search.

`--dry-run` runs the *same* `select_representative` against candidates grouped from the
archive's own metadata (`cli/search.py::_first_deduplicated_match`), rather than the
catalog — reading the whole archive's central directory once (still no member content)
before returning anything, since the archive's member order does not guarantee a title's
translations stay adjacent. This satisfies the dry-run/real-run parity driver at the cost
of turning a near-instant preview into a several-second one whenever
`one_subtitle_per_title` is on; that trade was judged the right default (see
Consequences).

## Rationale

Option 1 is the cheapest but has no defense against the exact failure mode this decision
sets out to avoid: a file that is largest for the wrong reason. Option 2 solves that but
overshoots — it optimizes for "typical," which on real duplicate groups actively prefers a
less complete file over a legitimate, larger one that is not actually an outlier by any
measure, and its headline parameter (the 20%/80% trim) is nearly inert at the group sizes
the corpus actually has. Option 4 would produce a marginally more accurate ranking than
byte size, but at a cost (opening and parsing roughly half the corpus's titles) that
directly works against the goal of *reducing* per-search cost, for an accuracy gain the
percentile evidence does not show byte size to need: the two thresholds already separate
"ordinary variation" from "genuine anomaly" with wide margins (×1.4 vs. ×2.0 vs. a tail
reaching ×189; 0.58 vs. 0.5 vs. a tail reaching 0.0275). Option 3 is the smallest change
that fixes Option 1's actual failure mode using data already free at index time.

## Consequences

### Positive

- Search cost drops for the 54% of titles with duplicate translations, with zero added
  I/O: everything is computed from `size_bytes`, free at `corpus index` time.
- The pick is deterministic and reproducible from catalog state alone.
- `search/planner.py::enqueue`'s existing paginated, transactional write loop is
  unmodified; all new complexity is isolated in a dedicated pre-pass
  (`_prepare_dedup_winners`) and a small, independently unit-tested pure function
  (`search/dedup.py::select_representative`), reused as-is by `--dry-run`.
- `--dry-run` and a real run apply the identical algorithm to decide a group's winner —
  the dry-run/real-run parity driver holds without a documented exception.

### Negative

- `--dry-run` pays a real cost for that parity: `_first_deduplicated_match` reads the
  whole archive's metadata before returning anything, instead of stopping at the first
  match. Still no member content read (central directory only, the same bound
  `corpus index` itself operates under), but a preview that used to be near-instant now
  takes a few seconds on the full corpus. `select.one_subtitle_per_title: false` restores
  the previous first-match behavior for anyone who wants the faster preview back.
- A catalog indexed before `subtitle_files.size_bytes` existed degrades a *real run's*
  deduplication silently: a `NULL` size is treated as `0`, and a group where every
  candidate is `NULL` falls back to the lowest-`opensubtitles_file_id` tie-break with no
  signal at all. `corpus index` must be rerun after upgrading for the ranking to mean
  anything. `--dry-run` is unaffected — it reads sizes from the archive directly, never
  from the catalog.
- The two thresholds are hardcoded constants (`search/dedup.py`), not a manifest-tunable
  parameter — calibrated against evidence, not exposed as a knob, since no case for
  per-search tuning has come up yet.

### Risks

- The thresholds are calibrated specifically against the `en`/`v2024`/`raw` archive. A
  different language or OPUS release could plausibly have a different size-distribution
  shape (a different mix of forced/full/SDH subtitles), which nothing here would detect
  automatically. Mitigation: both constants live in `search/dedup.py` with their
  calibrating percentiles documented inline — re-measuring and adjusting them for a new
  corpus shape is a small, self-contained change.

## Related

- ADR-0015 — never read subtitle content outside a search (the property `size_bytes`
  preserves: it comes from the zip central directory, not a decompressed member).
- ADR-0018 — split catalog and run databases (the temp-table pre-pass this decision adds
  lives entirely on `catalog_conn`, per that split).
- ADR-0019 — dry-run/real-run parity as a decision driver, which this decision extends to
  `select.one_subtitle_per_title` rather than carving out an exception for.
- `search/dedup.py::Candidate`/`select_representative`; `search/planner.py::
  _prepare_dedup_winners`/`_grouping_query`/`_matching_page_query`/`_filter_clauses`;
  `cli/search.py::_first_deduplicated_match`/`_first_match`;
  `corpus/layout.py::CorpusEntry.size_bytes`/`parse_entry`/`iter_corpus`;
  `cli/corpus.py::_flush_catalog`; `manifest/model.py::SelectConfig.one_subtitle_per_title`.
- CLAUDE.md §6, "OPUS OpenSubtitles corpus" — the subtitle-type/duplication pitfalls this
  decision responds to.
- CHANGELOG.md's "Known limitations" — the `--dry-run` performance and stale-catalog
  entries this decision's Negative consequences are recorded under.
