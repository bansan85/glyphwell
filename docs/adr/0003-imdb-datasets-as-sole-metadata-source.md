# ADR-0003: Use the official IMDb datasets as the sole metadata source

**Status**: Accepted
**Date**: 2026-08-24

## Context

The OPUS OpenSubtitles corpus organises files by IMDb identifier. Turning that identifier
into a usable title, type and year needs a metadata source keyed by the same identifier.

The TMDB daily ID exports were the initial candidate, for the four kinds `movie_ids`,
`tv_series_ids`, `adult_movie_ids` and `adult_tv_series_ids`. Checking the actual file
content settled the question: each line of a TMDB export carries only `adult`, `id`,
`original_title` (or `original_name`), `popularity` and `video`. There is no IMDb identifier
in the exports at all, so they cannot be joined to the corpus directly.

Bridging that gap would require either one TMDB `/find` API call per identifier, or an
approximate match on normalised title and year.

## Decision Drivers

- Must join exactly on the identifier the corpus already carries, with no fuzzy matching.
- Must give the title, the type, the year, and the episode-to-series relationship.
- Should work offline once fetched, and should not need an API key.

## Considered Options

### Option 1: Official IMDb datasets only

- **Pros**: `title.basics.tsv.gz` is keyed by `tconst`, exactly the corpus identifier, so
  the join is exact; `title.episode.tsv.gz` gives the episode-to-series link; fully offline;
  no API key; refreshed daily.
- **Cons**: No popularity measure of any kind.

### Option 2: TMDB exports plus the TMDB `/find` API

- **Pros**: Localised titles; popularity and an explicit adult flag.
- **Cons**: Needs an API key; one network call per identifier to bridge to IMDb, for
  hundreds of thousands of identifiers; a cache to maintain; and the exports alone still
  cannot be joined.

### Option 3: Both, behind pluggable providers

- **Pros**: Defers the choice.
- **Cons**: Two sources to keep consistent, and a best-effort title-and-year link on the
  critical path for a fact the IMDb datasets already give exactly.

## Decision

Use the **official IMDb datasets as the only metadata source**: `title.basics.tsv.gz` for
type, titles, year, adult flag and runtime, and `title.episode.tsv.gz` for the season and
episode numbers and the parent series. No third-party source is introduced.

## Rationale

The corpus identifier is a `tconst`. Any source not keyed by `tconst` has to be reached
through an approximate match, and approximate matching is being paid for information that
the IMDb datasets already provide exactly. TMDB's only genuine addition was popularity,
which nothing in the current design consumes.

## Consequences

### Positive

- Exact join, no title normalisation and no confidence score anywhere in the design.
- Fully offline after the fetch; no API key and no rate limit.
- One import path to test instead of two sources to reconcile.

### Negative

- No popularity signal, so a "search only well-known titles" filter is not currently
  expressible.
- Titles come in IMDb's primary and original forms only; no localised variants.

### Risks

- If a popularity filter becomes necessary, the correct move is `title.ratings.tsv.gz`
  (`averageRating`, `numVotes`), which is also keyed by `tconst`, rather than reintroducing a
  third-party source. This is recorded in `CLAUDE.md` so the question is not reopened
  without the context.

## Related

- `metadata/imdb_datasets.py`, `metadata/resolver.py`, the `titles` table in `db/schema.sql`.
- TMDB daily ID exports: <https://developer.themoviedb.org/docs/daily-id-exports>
