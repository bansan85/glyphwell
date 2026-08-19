# ADR-0005: Analyse sliding windows of sentences and resume inside a file

**Status**: Accepted
**Date**: 2026-08-24

## Context

A search must be interruptible and resumable. The explicit requirement was that stopping
part-way through a subtitle must not force re-analysing that whole subtitle from the start.

The OPUS `raw` XML gives each sentence an `<s id="...">` attribute. That attribute is
ordered, but it is not guaranteed to be contiguous or purely numeric, so it can only be
treated as an opaque ordinal.

## Decision Drivers

- Must be able to resume inside a file, not only between files.
- Must never lose a committed result, and must never advance the cursor past work that was
  not committed.
- Must be idempotent, since a resume necessarily replays the boundary.
- Should keep enough surrounding context for the model to be useful.
- Should keep the number of model calls economical.

## Considered Options

### Option 1: Sliding window of N sentences with overlap

- **Pros**: One model call per window, so the cursor advances at window granularity;
  overlap preserves context across the boundary; the call count is tunable per manifest.
- **Cons**: Overlap means some sentences are analysed twice, and a window is the smallest
  unit of lost work on a crash.

### Option 2: One model call per sentence

- **Pros**: Resumes at exactly the interrupted line.
- **Cons**: A model call per line is prohibitive across hundreds of thousands of files, and
  a single line carries almost no context.

### Option 3: One model call per file

- **Pros**: Full context, simplest possible bookkeeping.
- **Cons**: An interruption discards the whole file, which is precisely what was ruled out.

## Decision

A file is cut into **sliding windows of `chunk.size` sentences with `chunk.overlap`
overlap**, one model call per window. Progress is recorded per `(run, file)` in `run_files`.

`last_sentence_index` is the **authoritative** cursor: the position, in the sentence stream
of the file, of the last sentence covered by a window whose result is committed.
`last_sentence_id` stores the corresponding `<s id>` for traceability only.

Four invariants make this safe:

1. **One transaction per window**, writing the result and the cursor advance together.
2. **Idempotence** through `UNIQUE (run_id, file_id, chunk_index)` on `results` combined
   with `INSERT OR IGNORE`.
3. **Deterministic queue order**, `ORDER BY rel_path` in `search/planner.py`, so a resume
   walks the same sequence and `chunk_index` always denotes the same window.
4. **Clean shutdown**: SIGINT finishes the current window, commits, and marks the run
   `paused`; it never leaves a file `in_progress` with an inconsistent cursor.

## Rationale

The cursor is an integer position rather than the `<s id>` value because `<s id>` is an
opaque ordinal: it cannot be compared or incremented reliably, so it cannot answer the
question "resume after this point". Keeping the id alongside costs one column and makes a
cursor readable against the source file during debugging.

Invariants 1 and 2 are what make a crash harmless in both directions. Without the single
transaction, a crash between the two writes either loses a result or skips one. Without the
uniqueness constraint, the replayed boundary window duplicates its result. Invariant 3 is
what makes `chunk_index` meaningful at all: it is a position in a sequence, so the sequence
must be reproducible.

## Consequences

### Positive

- Worst-case lost work on a crash is one window.
- Replaying a window is always safe, so resume needs no special-casing.
- The cost and context trade-off is set per manifest rather than in code.

### Negative

- Overlapping sentences are analysed more than once, so `chunk.overlap` is paid on every
  window.
- `chunk_index` depends on the queue order, so the ordering in the planner is now a
  correctness requirement rather than a convenience.

### Risks

- Changing `chunk.size` or `chunk.overlap` re-partitions the file, invalidating the meaning
  of stored `chunk_index` values. This is contained by ADR-0004: both fields are part of the
  manifest, so changing either changes the manifest hash and starts a new run.

## Related

- `search/checkpoint.py`, `search/planner.py`, `search/engine.py`, `corpus/chunker.py`,
  and the `run_files` and `results` tables in `db/schema.sql`.
- ADR-0004 (manifest hash), ADR-0006 (invalidating a single file).
