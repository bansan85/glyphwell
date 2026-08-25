# ADR-0017: Eagerly materialize the search work queue rather than stream it

**Status**: Accepted
**Date**: 2026-08-26

## Context

`SearchEngine._run()` calls `planner.enqueue()` to completion — every file matching the
manifest's `select` filters is written to `run_files` — before `_process_queue()` submits
a single chunk to Ollama. On a real corpus (`titles`: 12,734,722 rows; `subtitle_files`:
1,274,671 rows), with broad `select` filters, this join covers close to the whole corpus.

Investigating why this phase was "way too long" found two real bugs, now fixed (see
`CHANGELOG.md`):

- `RunFilesRepository.enqueue_many`'s batched `INSERT OR IGNORE` ran with no explicit
  transaction, so on the autocommit connection each of the ~1.27M matching files became
  its own commit.
- `enqueue`'s `SELECT` cursor stayed open across every one of those writes; in WAL mode an
  open reader pins the checkpoint to where its snapshot began, so none of that run's own
  writes could ever be reclaimed. The WAL had grown to **13 GB** next to a 2.3 GB main
  database file, on a mechanical HDD (`WDC WD10SPZX`) — every read paid for reconciling
  that WAL on top of already-slow random I/O.

`planner.enqueue` now paginates with keyset pagination on `sf.file_id`, commits one
explicit transaction per page, and `SearchEngine` no longer re-runs it on every resume
(only a freshly created run needs it). `db/connection.py` also raises the page cache and
checkpoints the WAL on close. Even so, a first-time scan of this corpus still takes on the
order of **fifteen to twenty minutes** on this disk before the first Ollama call — a real,
if now one-time-per-run, wait. This raised the question: does the queue need to be fully
built before processing starts, or could files be handed to Ollama as they are discovered,
overlapping the scan with the first model calls?

## Decision Drivers

- Repeated `search run --limit N` invocations (used to iterate on a manifest's prompt)
  must sample the *same* N files each time, or comparing two prompt tweaks is meaningless.
- A run's scope — which files it covers — must be fixed and auditable from the moment it
  is created, not a function of timing (how far a concurrent scan had gotten, or whether
  `corpus index` was re-run between two resumes of the same paused search).
- Progress reporting (`done / planned`) needs a stable denominator, not one that grows
  while the run is already in flight.
- Should minimize time-to-first-Ollama-call where doing so does not cost any of the above.
- A per-file resume's own correctness (`last_sentence_index`, `chunks_done`) does not
  depend on this decision either way: it is local to `(run_id, file_id)`
  (`search/checkpoint.py`), independent of the order other files are considered in.

## Considered Options

### Option 1: Keep the queue eagerly materialized (status quo, now with a faster scan)

- **Pros**: `run_files` is populated in `iter_work`'s own processing order (`ORDER BY
  sf.rel_path`), so "the queue" and "the order files are processed in" are the same fixed
  list from the moment `enqueue` finishes — `--limit` and a run's scope are trivially
  reproducible. The recent fixes (batched transactions, no reader pinning the WAL, a
  larger page cache, no re-scan on resume) already turn a cost that used to repeat on
  every resume into a one-time cost per freshly created run.
- **Cons**: that one-time cost is still real — tens of minutes on a large, cold corpus on
  slow storage — and Ollama sits idle for all of it.

### Option 2: Fully lazy/streamed queue — start processing as files are discovered

- **Pros**: hides the scan's latency behind the first model calls instead of paying it
  upfront.
- **Cons**: `enqueue` discovers matches by keyset-paginating on `sf.file_id` — cheap and
  index-backed, but unrelated to `rel_path`, the order processing actually uses. Streaming
  admission from that discovery order would process files in whatever order the scan
  happens to encounter them, not `ORDER BY rel_path`: two `--limit N` trial runs could
  sample different files depending on scan/thread timing, and a run's scope would no
  longer be fixed at creation — it would depend on how far the scan had gotten before a
  pause, or on a `corpus index` run racing the scan. Making the scan itself paginate by
  `rel_path` instead (to keep discovery and processing order aligned) has no supporting
  index today: `idx_subtitle_files_scan` is `(opus_version, language, rel_path)`, not a
  bare `rel_path` ordering usable once other `select` filters (title type, year) are
  applied — a new index and a materially larger change for what the fix above already
  reduced to a one-time cost.

### Option 3: Split the difference — eager materialization, but a faster scan

- **Pros**: preserves every property of Option 1 exactly; each individual improvement
  (transaction batching, not pinning the WAL, a bigger cache, skipping the rescan on
  resume) is independently low-risk and already landed.
- **Cons**: does not eliminate the one-time wait on a cold cache and slow storage, only
  shrinks it — no architectural change removes it entirely.

## Decision

Keep the search work queue **eagerly materialized**: `planner.enqueue()` still runs to
completion before `_process_queue()` starts. What changed is how cheaply it does so
(Option 3's fixes), not whether it does so (rejecting Option 2).

## Rationale

The value Option 2 would buy — hiding a scan behind the first Ollama calls — shrank
substantially once the actual bug (unbatched transactions pinning an unbounded WAL) was
fixed: what used to be an unbounded, ever-repeating cost is now a one-time, bounded cost
per freshly created run, already skipped entirely on resume. What Option 2 would cost —
deterministic `--limit` sampling and a run's scope being fixed at creation — are exactly
the properties `planner.py`'s own docstring already calls out as invariants ("Order is an
invariant, not a detail"), and reproducing a manifest-tuning trial run depends on them
directly. Paying a bounded, shrinking, one-time cost is a better trade than giving up
reproducibility for a benefit that mostly disappeared once the underlying bug was fixed.

## Consequences

### Positive

- No ordering or reproducibility guarantee was sacrificed for speed.
- The bug fix already applied (batched transactions, no reader pinning the WAL, larger
  page cache, no re-enqueue on resume) turns "always slow" into "slow once per new run,
  instant on resume" — most of the pain this ADR was triggered by is already gone.
- The mental model stays simple: two phases, build then process, in that order, always.

### Negative

- A brand-new run against a large, cold corpus on slow storage still pays a real wait
  (measured ~15-20 minutes on the reporter's mechanical HDD for ~1.27M files) with Ollama
  idle throughout, and no further architectural lever is planned to remove it.

### Risks

- If this wait becomes intolerable at a larger corpus scale, revisit as a new ADR —
  e.g. re-keying `enqueue`'s pagination on `rel_path` (would need a new index; `select`
  filters combined with a bare `rel_path` ordering aren't served by
  `idx_subtitle_files_scan` today) so that streaming becomes order-preserving. Explicitly
  out of scope here.

## Related

- `search/planner.py`, `search/engine.py`, `db/connection.py`.
- ADR-0005 (the resume invariants, including deterministic queue order, that this
  decision preserves), ADR-0012 (cross-file concurrency in the same engine).
