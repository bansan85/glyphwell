# ADR-0015: Drop the per-file freshness checksum

**Status**: Accepted
**Date**: 2026-08-25

## Context

ADR-0006 based a subtitle file's freshness on the pair `(opus_version, sha256)`:
`corpus refresh` would recompute a member's checksum and, if it differed from the stored
one, delete only that file's `results` and reset its `run_files` cursor. Revisiting that
decision surfaced three things:

- `opus_version` is already part of `subtitle_files`' natural key
  (`UNIQUE(opus_version, language, rel_path)`). A new OPUS release already produces new
  rows on its own, without needing a hash to notice anything.
- The mechanism was never actually wired up: `run_files.file_sha256` was written by
  nothing (`RunFilesRepository.enqueue_many` never set it), and `RunFilesRepository.reset`
  / `ResultsRepository.delete_for_file` were called by nothing but the never-implemented
  `corpus refresh`, which had stayed a `NotImplementedError` stub.
- The premise that motivated it — that a subtitle's content can change while staying at
  the same `(opus_version, language, rel_path)` — does not hold for OPUS/opensubtitles.org
  in practice: an improved or corrected subtitle is uploaded under a new
  `opensubtitles_file_id`, and therefore a new `rel_path`, rather than mutating an
  existing archive member in place.

Without that premise, ADR-0006's Option 2 ("new IMDb identifiers only") is not the
lossy choice it was assumed to be: a newly-appeared subtitle is a new
`subtitle_files` row regardless, picked up by re-running `corpus index`.

## Decision Drivers

- Do not pay a full-corpus read (ADR-0006's own stated cost) for a case that does not
  occur.
- Do not carry schema columns and repository methods that no code path populates or
  calls.
- A newly-appeared file must still reach every relevant, already-running search.

## Considered Options

### Option 1: Keep the mechanism, finish wiring it up

- **Pros**: Matches the original design; `corpus refresh` would finally do something.
- **Cons**: Builds out a full-corpus hashing pass to defend against a scenario that, on
  reflection, does not happen on this corpus. The cost ADR-0006 accepted was justified by
  a threat model that turned out to be wrong.

### Option 2: Drop the per-file checksum entirely

- **Pros**: `corpus index` goes back to reading only the central directory — no content
  read at all. Removes dead schema (`subtitle_files.sha256`, `run_files.file_sha256`) and
  dead code (`set_hash`, `iter_stale`, `reset`, `delete_for_file`, the `refresh` stub).
- **Cons**: If a subtitle ever *did* change in place at a stable `rel_path`, nothing would
  notice. Accepted: believed not to occur for this corpus, and re-fetching a fresh OPUS
  release is the recourse if it ever does.

## Decision

Drop the per-file checksum entirely (Option 2): `subtitle_files.sha256`,
`run_files.file_sha256`, `corpus index --rehash`,
`SubtitleFilesRepository.set_hash`/`iter_stale`, `RunFilesRepository.reset`,
`ResultsRepository.delete_for_file`, and the `corpus refresh` command are all removed.
`corpus/hashing.py` (`sha256_file`/`sha256_stream`) is untouched: it still backs the
unrelated archive-download checksum (`corpus_downloads.sha256`, `corpus fetch --hash`).

A subtitle that newly appears under a new `opensubtitles_file_id` is covered without any
dedicated mechanism: re-running `corpus index` adds its row, and
`RunFilesRepository.enqueue_many` is already idempotent and documented to complete the
queue of an existing run when new files appear in the corpus.

## Rationale

The mechanism cost a full-corpus read to defend against a mutation pattern that does not
occur on this corpus, and the code paths meant to consume its output were never written.
Removing it deletes dead schema and dead code rather than finishing an implementation
whose premise no longer holds.

## Consequences

### Positive

- `corpus index` no longer reads any subtitle content — pure central-directory
  cataloging, faster and simpler.
- Removes schema columns, repository methods, and a CLI stub that no code path used.
- A newly-appeared file is already covered by existing, exercised code
  (`enqueue_many`'s idempotent completion of a run's queue).

### Negative

- No detection of a subtitle mutating in place at an unchanged `rel_path`, should that
  assumption turn out to be wrong for some corner of the corpus.
- `subtitle_files.size_bytes` loses its only writer (it was populated as a side effect of
  hashing) and stays `NULL` going forward. Left as-is here — it is a size, not a hash, and
  out of this decision's scope — but noted for whoever next looks at that column.

### Risks

- If a subtitle is ever found to change in place, the mitigation is a fresh `corpus fetch`
  of the affected release rather than a targeted re-analysis; this is more expensive per
  incident but the incident itself is believed not to occur.

## Related

- Supersedes ADR-0006.
- `db/schema.sql`, `db/migrations.py` (version 3), `db/repositories.py`,
  `cli/corpus.py::index`.
