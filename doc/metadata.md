# Step 2 — resolving titles from the IMDb datasets

The corpus organises subtitles by IMDb identifier, but an identifier alone is not a
usable title. Step 2 downloads the official IMDb datasets and joins them onto that
identifier so a search can filter and report on the title, its type, its year, and, for
an episode, its series, season and number.

## In one command

```bash
uv run glyphwell metadata fetch-imdb    # ~1 GB total, once, then daily if refreshed
uv run glyphwell metadata import-imdb   # imports into the titles table
```

`fetch-imdb` downloads `title.basics.tsv.gz` and `title.episode.tsv.gz` into
`<data-dir>/downloads`. `import-imdb` reads them and populates `titles`; episodes are
processed after base titles, so that attaching an episode to its series finds a row that
already exists. Each file gets its own progress bar, driven by bytes read from disk —
not a row count, which for `title.basics` would mean a full pass over a gigabyte-plus
file before showing anything.

## Where the data comes from

The [official IMDb non-commercial datasets](https://datasets.imdbws.com/), republished
daily, no API key. Two files are enough — see ADR-0003 for why they were chosen over a
third-party source such as TMDB:

- `title.basics.tsv.gz` — `tconst`, type, primary/original title, year(s), adult flag,
  runtime.
- `title.episode.tsv.gz` — `tconst`, `parentTconst`, season number, episode number.

The join key, `tconst`, is exactly the (bare) IMDb identifier the corpus tree already
carries — see [Internal layout](corpus.md#internal-layout).

## Already have the datasets?

`import-imdb --source-dir` points at any directory containing either form of the two
files — `download`'s own `.tsv.gz`, or the plain `.tsv` IMDb's own download page serves:

```bash
uv run glyphwell metadata import-imdb --source-dir /path/to/imdb/datasets
```

This skips `fetch-imdb` entirely if you already fetched the datasets by hand.

## Options

| Option | Command | Default | Effect |
|---|---|---|---|
| `--force` | `fetch-imdb` | — | Re-downloads even if the files are already present. |
| `--source-dir` | `import-imdb` | `<data-dir>/downloads` | Directory holding the datasets, compressed or already decompressed. |

## Two-pass import

`import_basics` and `import_episodes` write to the same `titles` table but never
overwrite what the other one knows:

- `import_basics` always carries authoritative values for the basics columns, and
  coalesces the parent/season/episode columns against whatever is already stored — a
  re-import can't blank out a link.
- `import_episodes` only ever updates `parent_imdb_id`, `season_number`, and
  `episode_number` on a row that must already exist. It never touches, and never has to
  invent a value for, columns such as the non-nullable adult flag.

See ADR-0010 for the full reasoning and the options that were ruled out. One consequence
worth knowing: **run order matters**. If `import_episodes` runs for a `tconst` that
`import_basics` has not written yet, that link is silently dropped rather than erroring
— `import-imdb` always runs the two in the right order, but a partial or interrupted
`import_basics` can leave a real gap, closed by simply rerunning `import-imdb`.

## Traceability

Each completed pass leaves a row in the `imports` table:

```bash
sqlite3 data/glyphwell.db \
  "SELECT source, file_name, row_count, imported_at FROM imports ORDER BY imported_at DESC"
```

| Column | Content |
|---|---|
| `source` | `imdb_basics` \| `imdb_episode` |
| `file_name` | Name of the file imported. |
| `row_count` | Rows written (`import_basics`) or updated (`import_episodes`). |
| `imported_at` | When the pass completed. |

## Performance

Both files together are on the order of 22 million rows. `import_basics`/
`import_episodes` read them positionally (not through `csv.DictReader`) and commit in
batches of 50 000 rows — see CLAUDE.md §6 for what was measured and why. `titles` also
carries no secondary index (ADR-0011): the only lookup this project performs is
`imdb_id -> title`, already served by the primary key, and maintaining an index whose
keys don't correlate with the file's insertion order was measured to roughly halve
throughput and to degrade further as the table grows.

In practice the dominant remaining cost is disk write latency, not Python: on a
mechanical (HDD) disk, commit latency alone can keep the import close to an order of
magnitude slower than on an SSD. If `import-imdb` feels slow, point `--database` (or
`GLYPHWELL_DATABASE`) at your fastest local disk — the source `.tsv` files can stay
wherever they were downloaded, since reading them is sequential.

## Troubleshooting

**"neither title.basics.tsv.gz nor title.basics.tsv found in …"** — `import-imdb` looked
in `<data-dir>/downloads` (or `--source-dir`) and found neither form of the file. Run
`fetch-imdb` first, or point `--source-dir` at wherever you already have the datasets.

**"missing column '…' in …"** — the header of the TSV doesn't contain a column
`import_basics`/`import_episodes` expects. This would mean IMDb changed the dataset's
columns; check the file against the shape described above before reporting it further.

**"…: N columns, expected M"** — a row's column count doesn't match the header. IMDb's
datasets are not CSV-quoted (see CLAUDE.md §6): this error means the row is genuinely
malformed, not that a title contains a comma or a quote.

## What's next

Titles resolve from an identifier, but nothing yet consumes them at search time: the
`search` group (chunking, prompting, resuming) is not implemented.
