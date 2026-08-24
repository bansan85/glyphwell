# ADR-0008: Never extract the corpus archive

**Status**: Accepted
**Date**: 2026-08-25

## Context

OPUS ships OpenSubtitles as one zip per (release, language). The English `v2024` / `raw`
archive is **35.8 GB** and holds several hundred thousand members, one XML file per
subtitle.

The project skeleton assumed the archive would be unpacked: `corpus/opus.py` exposed
`extract_archive`, `Settings.corpus_dir` was documented as the root of an extracted tree,
`subtitle_files.rel_path` was relative to that root, and `corpus_downloads` carried an
`extracted_at` column and an `extracted` status. Nothing had been built on that assumption
yet, so the storage shape could still be settled before the reader, the chunker and the
planner were written against it.

## Decision Drivers

- Must not ask for twice the size of the archive on disk.
- Must give random access to any single subtitle: the resume cursor of ADR-0005 works file
  by file, and the planner walks files in a deterministic order.
- Should keep the integrity of the corpus checkable cheaply, since ADR-0006 makes staleness
  a content question.
- Should keep the number of filesystem objects reasonable.

## Considered Options

### Option 1: Extract to a directory tree

- **Pros**: the simplest possible reader, taking a `Path`; the corpus can be inspected with
  ordinary tools (`grep`, `ls`); extraction is a one-off cost.
- **Cons**: roughly doubles the disk requirement, to about 75 GB; creates hundreds of
  thousands of inodes, which is slow to walk and painful to delete; extraction is a long
  step that cannot be resumed; the tree can drift from the archive it came from, so the
  corpus no longer has a single identity.

### Option 2: Read members from the zip on the fly

- **Pros**: one artefact, one `sha256`; disk cost is exactly the archive; random access to
  any member through the zip central directory; nothing to keep in sync.
- **Cons**: the central directory is loaded into memory when the archive is opened; the
  corpus is no longer readable with ordinary file tools; concurrent reads need care.

### Option 3: Convert to an intermediate store (SQLite blobs, or one large JSONL)

- **Pros**: a single file, and a storage format under our control.
- **Cons**: a full-corpus rewrite on top of the download, a second format to keep in step
  with OPUS releases, and the loss of the member names that carry the IMDb identifier
  (ADR-0003). It buys nothing that option 2 does not already provide.

## Decision

**The zip archive is the corpus.** It is never extracted. `CorpusArchive` opens it once and
serves members through `ZipFile.open`, decompressing as the caller consumes the stream;
nothing is written to disk and no member is materialised in memory.

Three consequences are load-bearing for the rest of the project:

- `subtitle_files.rel_path` stores the **full member name, prefix included**
  (`OpenSubtitles/raw/en/1999/0133093/3660124.xml`). It is the only key `open_member`
  accepts, so `parse_entry` must absorb the `<corpus>/<preprocessing>/` prefix rather than
  assume the path starts at the language.
- `iter_corpus` takes an open `CorpusArchive`, not a directory root, and
  `corpus/reader.py` will read an `IO[bytes]` rather than a `Path`.
- There is no extraction step to record: `extract_archive` is gone, `extracted_at` became
  `verified_at`, and the `extracted` status was removed.

## Rationale

The disk saving is the visible argument, but the decisive one is identity. ADR-0006 defines
freshness as `(opus_version, sha256)`; with an extracted tree that hash is either recomputed
over hundreds of thousands of files or not checked at all, and the tree can be edited
without anything noticing. With a single archive, "has the corpus changed?" is one hash of
one file.

Random access, which is what an extracted tree seems to offer, is already provided by the
zip format: the central directory maps every member to an offset. Extraction adds no
capability; it only adds a copy.

The costs are real but bounded and measurable, where the costs of option 1 grow with the
corpus.

## Consequences

### Positive

- Disk requirement is the size of the archive, not its double.
- The corpus is one artefact with one `sha256`, which makes `corpus refresh` cheap to
  reason about.
- No extraction step means no half-extracted state to detect or clean up.
- Deleting or moving the corpus is one file operation.

### Negative

- `zipfile` reads the whole central directory when the archive is opened: on the order of
  150 MB of resident memory for 400 000 members. This is paid once per handle.
- Concurrent reads on one handle serialise, so the search engine must hold **one
  `CorpusArchive` per thread**.
- The corpus can no longer be inspected with ordinary file tools.
- A corrupt archive costs a full re-download; there is no partial re-extraction.

### Risks

- **Central directory memory growing with the corpus.** Bounded by the fact that it is
  proportional to the member count, not to the corpus size, and it is paid per handle: the
  concurrency setting caps how many handles exist.
- **Members that are not plain `.xml`.** If a release ever nested a second level of
  compression, silently skipping those members would lose text. `CorpusArchive.summarize`
  therefore counts members whose suffix is outside `SUBTITLE_SUFFIXES` and `corpus fetch`
  reports them, instead of guarding defensively against a case that does not exist.

## Related

- `corpus/archive.py` holds the primitive; `corpus/layout.py` and `db/schema.sql` carry the
  consequences on `rel_path`.
- ADR-0002 (why the text is not copied into SQLite either), ADR-0006 (the `sha256` this
  makes cheap), ADR-0009 (how the archive is fetched).
