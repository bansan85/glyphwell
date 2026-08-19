# ADR-0006: Detect staleness with the pair (opus_version, sha256)

**Status**: Accepted
**Date**: 2026-08-24

## Context

OpenSubtitles keeps publishing better subtitles, and OPUS republishes the corpus as
versioned releases. A search that has already analysed a file must be able to notice that a
newer version of that file exists and re-analyse it, without discarding the rest of the run.

"Newer" had to be given a precise meaning before anything could be built on it.

## Decision Drivers

- Must detect that the content of a file changed, not merely that it was touched.
- Must invalidate only the affected file, preserving the rest of an expensive run.
- Should not depend on filesystem metadata, which does not survive copying or extraction
  reliably.

## Considered Options

### Option 1: The pair (opus_version, sha256)

- **Pros**: Content-addressed, so it detects real changes and ignores re-extraction that
  produces identical bytes; the OPUS release version is part of the identity of a file, so
  the same subtitle from two releases is two rows; invalidation is naturally per file.
- **Cons**: Requires hashing every file, which is a full read of the corpus.

### Option 2: New IMDb identifiers only

- **Pros**: Trivial, and no hashing.
- **Cons**: A file already analysed is never revisited, so an improved subtitle for a title
  already seen is ignored. This fails the requirement outright.

### Option 3: Timestamped rescan against mtime and size

- **Pros**: Cheap.
- **Cons**: Depends on filesystem metadata, which archive extraction, copying between disks
  and syncing all perturb; produces both false positives and false negatives.

## Decision

The freshness key of a file is the pair **`(opus_version, sha256)`**. `corpus refresh`
recomputes the `sha256`. If it differs from the stored value, the `results` rows of **that
file only** are deleted and its `run_files` rows return to `pending` with the cursor
cleared. A new OPUS release version produces new `subtitle_files` rows rather than mutating
existing ones, which is why `UNIQUE (opus_version, language, rel_path)` includes the version.

## Rationale

Only content hashing distinguishes "this subtitle actually changed" from "these bytes were
written again". Since the corpus is downloaded as archives and extracted, mtime carries no
usable signal, and size collides too easily for text.

Scoping invalidation to a single file is what makes the mechanism usable: a run over the
full English corpus is expensive, and a decision that discards it because one file improved
would simply not be run.

The full-corpus read that hashing requires is acceptable because it is bounded by disk
throughput, whereas the work it protects is bounded by model latency, which is orders of
magnitude slower.

## Consequences

### Positive

- Re-analysis is triggered by real content changes only.
- An improved subtitle costs one file worth of re-analysis, not a whole run.
- Independent of the filesystem, so the corpus can be moved between disks freely.

### Negative

- `corpus refresh` reads every file in the corpus, which is tens of gigabytes.
- The same subtitle present in two OPUS releases occupies two rows, and both can be
  analysed by the same run unless the selection in the manifest excludes one.

### Risks

- Hashing time growing with the corpus. Bounded by hashing in blocks, and by the fact that
  `refresh` is an explicit command rather than something a search does implicitly.

## Related

- `corpus/hashing.py`, and the `subtitle_files` and `corpus_downloads` tables in
  `db/schema.sql`.
- ADR-0002 (why there is no index to invalidate), ADR-0005 (the cursor that is reset).
