# ADR-0009: Use opustools as the OPUS index only, and httpx for the transfer

**Status**: Accepted
**Date**: 2026-08-25

## Context

`opustools` is the reference client for OPUS. It knows the contract of the index: the query
URL, the parameter names, the shape of a record, and the naming rule for downloaded
archives. That knowledge is worth depending on, because it changes when OPUS changes and
not when we do.

Its downloader is a different matter. Reading `OpusGet.get_files()` at version 1.8.3 shows
four properties, each verified in the source rather than assumed:

- it catches `urllib.error.URLError` and answers with a `print`, so it never raises;
- it sets no timeout;
- it cannot resume;
- it writes directly to the final file name.

On a 35.8 GB transfer that runs for hours, those combine badly. A connection dropped at 90 %
leaves a truncated archive under the final name, the call returns as if it had succeeded,
and the next run sees a file that is already there.

The same reading turned up a second class of trap, in the index rather than the downloader,
which shaped how the index is queried: in `raw` preprocessing the index answers with the
monolingual archive of *every* language paired with the requested one — a query for `en`
returned 51 candidates — and the "single space" wildcard that `OpusGet` suggests for
"any version" is sent as an empty `version=`, which the live API reads as "no version" and
answers with nothing.

## Decision Drivers

- Must not be able to mistake a truncated archive for a complete one.
- Must resume an interrupted transfer instead of restarting tens of gigabytes.
- Must show progress and throughput on a download measured in hours.
- Should keep OPUS's own index contract as the source of truth rather than reimplementing
  URL construction and archive naming.

## Considered Options

### Option 1: Use opustools end to end

- **Pros**: one dependency and almost no code of our own; naming and URLs stay correct by
  construction.
- **Cons**: the four defects above are in the middle of the function, not at its edges, so
  they cannot be worked around by a caller. Silent truncation in particular is a
  correctness problem, not an ergonomic one.

### Option 2: Drop opustools and hardcode the OPUS URL pattern

- **Pros**: no dependency, no local stub to maintain, one HTTP client.
- **Cons**: the URL shape, the parameter names and the archive naming rule become ours to
  track against a service we do not control; and the index is also what answers "which
  releases exist for this corpus", which would have to be reimplemented too.

### Option 3: opustools for the index, httpx for the bytes

- **Pros**: keeps the part of `opustools` that carries knowledge, replaces the part that
  carries defects; the transfer becomes ours to make resumable, observable and safe.
- **Cons**: two HTTP paths in one command, and a hand-written stub that must match the real
  signature.

## Decision

`OpusGet` is instantiated **only to read `.url` and to call `make_file_name()`**. Nothing is
downloaded through it, and `stubs/opustools/__init__.pyi` declares only those two members.

The transfer is a streaming `httpx` GET into `<archive>.zip.part`, resumed on a later run
with a `Range` header and renamed onto the final path only once the body is complete. The
`sha256` is computed as the bytes go past when the transfer starts from zero, since they are
in memory anyway; after a resume it is not, and `--hash` forces a separate pass.

Two details of the index query follow from the traps above and are load-bearing: the
monolingual record is selected on `target == "" and source == language`, not on `target`
alone, and "any version" is expressed by **omitting** the parameter.

## Rationale

The split follows where the value is. `opustools` is valuable as a description of a remote
contract and near-worthless as a file transfer, so it is used for the first and not the
second. Hardcoding the URL would have thrown away the description as well, to avoid a stub
of a dozen lines.

Writing to `.part` and renaming at the end is what makes truncation impossible to confuse
with success: the final name exists only after a complete body, and the rename is atomic on
both supported platforms.

Computing the hash inline only on a full transfer is a deliberate asymmetry. Hashing during
the transfer is free; hashing 35.8 GB afterwards takes minutes. Making it automatic after a
resume would punish exactly the case that is already the recovery path, so it is offered as
an explicit flag and reported as "not computed" otherwise.

## Consequences

### Positive

- An interrupted download resumes at the byte it stopped at, verified against the live
  service.
- A truncated transfer can never be taken for a complete archive.
- Progress, throughput and time remaining are available, because the transfer loop is ours.
- The archive URL is announced before any byte is fetched, so the user can decide against
  35.8 GB before committing to it.

### Negative

- Two HTTP stacks are exercised by one command: `urllib` inside `opustools` for the index
  URL construction, `httpx` for the index query and the transfer.
- A local stub must track the real `OpusGet.__init__` signature, which has twelve positional
  parameters in an order that is easy to get wrong.
- After a resume the `sha256` is unknown until `--hash` is run.

### Risks

- **Stub drift.** The stub is hand-written, so a change in `opustools` would be caught at
  runtime rather than by mypy. Bounded by using only two members, and by `resolve_archive`
  failing with a message that lists what the index actually returned rather than an
  assertion.
- **Index semantics changing.** Both traps found here were silent — a wrong-language archive
  and an empty version list, not an error. Each is covered by a regression test that pins
  the query and the filter.

## Related

- `corpus/opus.py` (`resolve_archive`, `download_corpus`), `stubs/opustools/__init__.pyi`,
  and the `corpus_downloads` table for the traceability of a download.
- ADR-0008 (what the downloaded archive is used for), ADR-0006 (why the `sha256` matters).
