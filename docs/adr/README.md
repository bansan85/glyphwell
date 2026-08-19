# Architecture Decision Records

This directory records the significant technical decisions taken on `glyphwell`, with the
context that produced them and the consequences accepted.

An ADR is written when a decision constrains later work: a data source, a storage model, a
correctness invariant. Routine choices (library versions, refactorings, bug fixes) are not
recorded here.

## Index

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-use-uv-for-packaging.md) | Use uv for packaging and dependency management | Accepted | 2026-08-24 |
| [0002](0002-sqlite-without-fts5.md) | Store the catalogue and run state in SQLite without FTS5 | Accepted | 2026-08-24 |
| [0003](0003-imdb-datasets-as-sole-metadata-source.md) | Use the official IMDb datasets as the sole metadata source | Accepted | 2026-08-24 |
| [0004](0004-yaml-manifest-as-search-definition.md) | Define a search with a hashed YAML manifest | Accepted | 2026-08-24 |
| [0005](0005-sliding-window-chunking-and-resume.md) | Analyse sliding windows of sentences and resume inside a file | Accepted | 2026-08-24 |
| [0006](0006-freshness-via-opus-version-and-sha256.md) | Detect staleness with the pair (opus_version, sha256) | Accepted | 2026-08-24 |
| [0007](0007-very-strict-typing.md) | Enforce very strict typing with no escape hatches | Accepted | 2026-08-24 |

## Statuses

- **Proposed** — under discussion.
- **Accepted** — decided, being implemented.
- **Deprecated** — no longer relevant.
- **Superseded** — replaced by a later ADR, which is named in the status line.
- **Rejected** — considered and turned down. Kept, because the reasoning is the value.

## Adding an ADR

1. Copy `template.md` to `NNNN-short-title-with-dashes.md`.
2. Fill it in. Keep it to one or two pages, and be honest about the drawbacks.
3. Add a row to the index above.

Accepted ADRs are not rewritten. When a decision changes, write a new ADR that supersedes
the old one and update the old one's status.
