# ADR-0002: Store the catalogue and run state in SQLite without FTS5

**Status**: Accepted
**Date**: 2026-08-24

## Context

`glyphwell` walks the OPUS OpenSubtitles corpus: several tens of gigabytes once
decompressed, hundreds of thousands of XML files. It has to know which titles and files it
has seen, and where each interrupted search stopped.

Two questions were separable. Where does the subtitle *text* live, and where does the
*state* live. The corpus is downloaded and extracted by `opustools`, so the XML files
already exist on disk in a stable layout.

## Decision Drivers

- Must survive a crash without losing committed work.
- Must support resuming a search, which needs transactional writes.
- Should not duplicate tens of gigabytes of text.
- Should not require a server process.

## Considered Options

### Option 1: SQLite for state, XML left on disk, no full-text index

- **Pros**: One file, no server, real transactions; the corpus is never rewritten or
  duplicated; the database stays small enough to copy or inspect.
- **Cons**: Every analysis re-reads the XML from disk; no way to pre-filter candidate files
  with a text query.

### Option 2: SQLite with an FTS5 index over the subtitle text

- **Pros**: Full-text pre-filtering could skip files before calling the model, which is the
  expensive step.
- **Cons**: Copies the entire corpus text into the database, roughly doubling storage;
  indexing several hundred thousand files is a long up-front cost; the index has to be
  invalidated whenever a file changes.

### Option 3: Append-only JSONL files

- **Pros**: Diffable and inspectable by hand.
- **Cons**: No transactions, so the resume cursor and its result cannot be committed
  atomically; deduplication at this scale becomes manual work.

## Decision

Use **SQLite with no FTS5**. The database holds the title catalogue, the file catalogue, run
state, resume cursors and results. The XML files on disk remain the only copy of the text
and are never rewritten or reindexed.

## Rationale

The storage cost of FTS5 was not the deciding factor; the invalidation cost was. ADR-0006
makes a file's `sha256` the freshness key, so any changed file would have to be re-indexed,
and the index becomes a second thing that can silently disagree with the corpus. Keeping the
XML authoritative removes that failure mode entirely.

Cheap text pre-filtering is still available without an index: ADR-0004 puts a pattern
pre-filter in the manifest, applied while streaming a file, which skips the model call
without needing a persistent index.

JSONL was ruled out by the transactional requirement alone, which is the core of ADR-0005.

## Consequences

### Positive

- No duplication of the corpus text.
- A file changing on disk invalidates only its own rows; nothing has to be reindexed.
- The single-transaction-per-window guarantee of ADR-0005 is available directly.

### Negative

- Selecting files by text content requires streaming them; there is no index to consult.
- Concurrency is bounded by SQLite. WAL mode and a busy timeout are set in
  `db/connection.py`; write concurrency stays modest by design.

### Risks

- If searches later turn out to be dominated by re-reading XML rather than by model
  latency, a derived index becomes worth revisiting. It can be added as a separate,
  rebuildable artefact without changing the schema.

## Related

- `db/schema.sql`, `db/connection.py`.
- ADR-0005 (resume transactions), ADR-0006 (freshness).
