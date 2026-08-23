# ADR-0012: Cross-file concurrency with thread-confined SQLite access

**Status**: Accepted
**Date**: 2026-08-25

## Context

A search calls the model once per chunk, and a single Ollama call is by far the slowest
step in the loop (network round trip plus model inference, seconds per call, against a
corpus of hundreds of thousands of files). Running calls one at a time would make
`Settings.concurrency` meaningless and leave the model server idle while the engine reads
sentences and writes results.

`db/connection.py` opens SQLite without `check_same_thread=False`: a connection may only
be touched from the thread that created it. `CorpusArchive` (ADR-0008) is likewise one
open zip handle per `(opus_version, language)`, and concurrent reads on a single handle
serialize.

## Decision Drivers

- Must overlap the latency of several in-flight model calls.
- Must preserve every invariant of ADR-0005 (one transaction per chunk, deterministic
  queue order) unchanged.
- Must not require a second SQLite connection, which would push the thread-affinity
  problem down one level and complicate the single-writer assumption the resume
  invariants rely on.
- Should not require rewriting the corpus or database layers around threading just to
  make searches faster.

## Considered Options

### Option 1: One connection, one archive handle, concurrency across files only

- **Pros**: worker threads run only `LlmClient.complete` — pure I/O, touching neither the
  database nor an archive handle — so nothing about ADR-0005's invariants changes; the
  owning thread does every DB write and every corpus read.
- **Cons**: one file's own chunks stay strictly sequential; a single very long subtitle
  gets no benefit from concurrency, only the fan-out across many files does.

### Option 2: A connection per worker thread

- **Pros**: would allow concurrency within one file's own chunk sequence too.
- **Cons**: `results`/`run_files` writes would need cross-connection coordination to keep
  "one transaction per chunk" meaningful; SQLite's own writer serialization would then
  just move the bottleneck elsewhere; multiplies `CorpusArchive` handles per the
  one-per-thread rule of ADR-0008, undermining the reason that rule exists (avoiding
  hundreds of thousands of open members).

### Option 3: Async I/O (`asyncio` + `aiosqlite`)

- **Pros**: single-threaded, sidesteps the thread-affinity question entirely.
- **Cons**: would require rewriting the database layer, the corpus archive layer, and the
  Ollama client around an async API, for a benefit — more in-flight requests than open
  files — that Option 1 already delivers at the granularity that actually matters (Ollama
  call latency, not local I/O).

## Decision

`SearchEngine` runs a `ThreadPoolExecutor` sized to `Settings.concurrency`. Worker threads
execute only `_complete_chunk` (render a prompt, call `LlmClient.complete`); the
connection, every repository call, and every `CorpusArchive` handle are touched
exclusively by the thread that owns `SearchEngine`. Concurrency is therefore **across
files**, never within one file's own chunk sequence.

## Rationale

The slow step is the network call to Ollama, not reading a chunk's sentences or writing
its result — so that call is the only thing worth overlapping. Confining every DB write
and archive read to one thread means ADR-0005's invariants hold exactly as designed, with
no cross-thread coordination to reason about. Option 1 buys the throughput that matters at
zero cost to correctness; Options 2 and 3 buy the same throughput, or less, at the cost of
touching layers whose current simplicity is itself a deliberate choice (ADR-0008's
one-handle-per-thread rule, the resume invariants of ADR-0005).

## Consequences

### Positive

- The resume invariants of ADR-0005 needed no change to support concurrency.
- Adding concurrency touched neither `db/connection.py`, `corpus/archive.py`, nor the
  schema.
- One file's failure (`OllamaError`) is isolated to that file via `run_files.mark_error`,
  without stopping the other files already in flight.

### Negative

- A single very long file gets no speed-up from `Settings.concurrency`: its chunks are
  analysed one at a time regardless of how high the setting is.
- Concurrency is bounded twice: by `Settings.concurrency`, and in practice by Ollama's own
  ability to serve concurrent requests (`OLLAMA_NUM_PARALLEL`, available VRAM). Raising the
  setting past what the model server can actually run in parallel buys nothing.

### Risks

- A future need for intra-file concurrency (splitting one huge file's chunks across
  workers) would need a second connection, or a queue in front of a single writer thread —
  deliberately out of scope here. Revisit as a new ADR if that need arises.

## Related

- `search/engine.py`, `db/connection.py`.
- ADR-0005 (the invariants this concurrency model preserves), ADR-0008 (the same
  one-handle-per-thread rule, applied to the corpus archive).
