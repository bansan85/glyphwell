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
| [0006](0006-freshness-via-opus-version-and-sha256.md) | Detect staleness with the pair (opus_version, sha256) | Superseded by 0015 | 2026-08-24 |
| [0007](0007-very-strict-typing.md) | Enforce very strict typing with no escape hatches | Accepted | 2026-08-24 |
| [0008](0008-never-extract-the-corpus-archive.md) | Never extract the corpus archive | Accepted | 2026-08-25 |
| [0009](0009-opustools-for-index-httpx-for-transfer.md) | Use opustools as the OPUS index only, and httpx for the transfer | Accepted | 2026-08-25 |
| [0010](0010-two-pass-imdb-import-with-episode-link-update.md) | Two-pass IMDb import: coalescing upsert plus a dedicated episode-link update | Accepted | 2026-08-22 |
| [0011](0011-drop-secondary-indexes-on-titles.md) | Drop the secondary indexes on `titles` | Accepted | 2026-08-25 |
| [0012](0012-cross-file-concurrency-thread-confined-sqlite.md) | Cross-file concurrency with thread-confined SQLite access | Accepted | 2026-08-25 |
| [0013](0013-revalidate-ollama-json-output-client-side.md) | Re-validate the model's JSON output client-side | Accepted | 2026-08-25 |
| [0014](0014-one-http-client-factory-and-a-bounded-tls-escape-hatch.md) | One HTTP client factory, and a bounded TLS escape hatch | Accepted | 2026-08-25 |
| [0015](0015-drop-per-file-freshness-hash.md) | Drop the per-file freshness checksum | Accepted | 2026-08-25 |
| [0016](0016-keep-only-the-episode-id-from-tv-compound-segments.md) | Keep only the episode id from the TV-episode compound segment | Accepted | 2026-08-25 |
| [0017](0017-eager-work-queue-not-streamed.md) | Eagerly materialize the search work queue rather than stream it | Accepted | 2026-08-26 |
| [0018](0018-split-catalog-and-run-databases.md) | Split the catalog and per-search run databases | Accepted | 2026-08-26 |
| [0019](0019-expand-series-imdb-ids-to-episodes.md) | Expand a series id in `select.imdb_ids` to its episodes | Accepted | 2026-08-26 |
| [0020](0020-deduplicate-subtitle-translations-by-size.md) | Deduplicate subtitle translations by size | Accepted | 2026-08-26 |
| [0021](0021-token-budget-chunking.md) | Size chunks from a token budget, not a fixed sentence count | Accepted | 2026-08-27 |
| [0022](0022-calibrate-the-response-ratio-from-observed-completions.md) | Calibrate the response ratio from a run's own observed completions | Accepted | 2026-08-27 |
| [0023](0023-cite-excerpts-by-line-range-not-id-list.md) | Cite excerpts by a line range, not a flat id list | Accepted | 2026-08-27 |

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
