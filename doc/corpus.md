# Step 1 — fetching the OpenSubtitles corpus

The first step drops the subtitle archive onto disk and verifies that it is usable.
Without it, none of the following steps have any material to work with.

## In one command

```bash
uv run glyphwell db init                      # once
uv run glyphwell corpus fetch --language en   # 35.8 GB for the v2024 release
```

The URL and size are announced **before** the transfer: nothing is committed without you
knowing what for. An interruption is not costly — see
[Resuming a download](#resuming-an-interrupted-download).

To validate the whole chain in seconds rather than hours, aim for a small OPUS corpus.
Here is the actual output of such a trial run:

```
$ uv run glyphwell corpus fetch --corpus Books --language en --version latest
OPUS archive: https://object.pouta.csc.fi/OPUS-Books/v1/raw/en.zip
Release v1, language en, preprocessing raw — about 11.4 MB
Destination: …\data\corpus
downloading ━━━━━━━━━━━━━━━━━━━━━ 11.4/11.4 MB 10.5 MB/s 0:00:00
 Archive              …\data\corpus\Books_v1_raw_en.zip
 Size                 11.4 MB
 Checksum             83279cfd5aab4bfcc54654134e35c5846027241b7a72f01774f102a815797d5c
 Subtitles            42
 Service files        3
Internal layout:
  OpenSubtitles/raw/en/1000/14250988_11617414_3_1/1957517352.xml
  OpenSubtitles/raw/en/1029/16288570_4131818_2_6/1957459444.xml
  OpenSubtitles/raw/en/1029/16288570_4131818_2_6/1957459443.xml
```

The `OpenSubtitles` corpus adds two levels to this layout, the year and the IMDb
identifier — see [Internal layout](#internal-layout).

## Where the corpus comes from

The corpus comes from [OPUS](https://opus.nlpl.eu/), which republishes OpenSubtitles in a
machine-usable form. `glyphwell` queries the OPUS index via
[`opustools`](https://pypi.org/project/opustools/) then downloads the archive.

Two choices are fixed by default:

- **`OpenSubtitles` corpus.** Changeable via `--corpus` — mostly useful for testing the
  chain on a small corpus.
- **`raw` preprocessing.** It's the only variant that keeps the text non-tokenized,
  usable as-is by an LLM. The `xml` variant splits each sentence into `<w>` tags —
  unusable here without re-joining the words.

The archive is named after these choices: `OpenSubtitles_v2024_raw_en.zip`. Several
releases can therefore coexist in `data/corpus/`.

## Which release?

`glyphwell` targets **`v2024`** by default, the most recent and most complete. The OPUS
index offers seven for OpenSubtitles:

| Release | Size of the `en` / `raw` archive |
|---|---|
| `v2024` *(default)* | 35.8 GB |
| `v2018` | 13.7 GB |
| `v2016` | 10.4 GB |
| `v2013` | 2.9 GB |
| `v2012` | 6.6 GB |
| `v2011` | 6.2 GB |
| `v1` | 42 MB |

A bigger release means more subtitles, hence a more thorough and longer search.
`--version v2018` targets an earlier release; `--version latest` asks the index for
whichever release it declares as most recent.

Each release is a separate acquisition: the archives coexist in `data/corpus/` and the
`corpus_downloads` table keeps one row per (release, language) pair.

## Options

| Option | Default | Effect |
|---|---|---|
| `--language`, `-l` | `GLYPHWELL_OPUS_LANGUAGE` (`en`) | Corpus language. |
| `--version` | `v2024` | OPUS release. `latest` asks for the most recent. |
| `--corpus` | `OpenSubtitles` | Name of the OPUS corpus. |
| `--dest` | `<data-dir>/corpus` | Directory to drop the archive into. |
| `--force` | — | Re-downloads even if the archive is already present. |
| `--hash` | — | Computes the checksum even when no transfer took place. |

## Why the archive is never extracted

Extracting the English archive would cost several extra tens of gigabytes and create
hundreds of thousands of files. `glyphwell` does without: the zip **is** the corpus, and
each subtitle is extracted from it on the fly at the moment it's read.

Three consequences:

- **A single artifact**, described by a single checksum. Verifying that the corpus hasn't
  changed means comparing a `sha256`, not walking hundreds of thousands of files.
- **An accepted memory cost**: `zipfile` loads the whole central directory on open, on the
  order of 150 MB for 400,000 members. That's the price of direct access to any given
  member, without a separate index.
- **One handle per thread.** Concurrent reads on the same handle serialize; the search
  engine will therefore open a handful of independent handles.

Nothing is ever written back into the archive: it is read-only for the entire life of the
project.

## Internal layout

Members of the OpenSubtitles archive follow this shape:

```
<corpus>/<preprocessing>/<language>/<year>/<imdb_id>/<opensubtitles_file_id>.xml
OpenSubtitles/raw/fr/2022/1596342/1957893755.xml
```

| Segment | Meaning |
|---|---|
| `OpenSubtitles` | name of the OPUS corpus |
| `raw` | preprocessing |
| `fr` | language of the subtitle |
| `2022` | year of the work |
| `1596342` | **bare** IMDb identifier — i.e. `tt1596342` in its canonical form |
| `1957893755` | identifier of the subtitle on opensubtitles.org |

The last two segments don't refer to the same thing: `1596342` identifies the **work**,
`1957893755` identifies **one specific translation** of that work. A single movie has one
IMDb identifier and as many subtitle identifiers as there are published versions. The
latter lets you trace back to the original listing:
`https://www.opensubtitles.org/en/subtitles/1957893755`.

It's this IMDb identifier that makes step 2 exact: the official IMDb datasets join
directly on it, without any approximate matching on title.

The archive also contains three service files at its root — `INFO`, `README`,
`LICENSE`. They are counted separately and are not subtitles.

If `corpus fetch` reports members with an **unexpected extension**, the assumption that
"all subtitles are plain `.xml`" has stopped holding for this release: that's worth
checking before going further, since it would be text that `glyphwell` wouldn't read.

## Resuming an interrupted download

The transfer is written to `<archive>.zip.part` and is renamed only once complete. An
incomplete archive can therefore never be mistaken for a complete one.

After an interruption — network, `Ctrl-C`, machine powered off — simply rerun the same
command:

```bash
uv run glyphwell corpus fetch --language en
```

The `.part` is resumed via the HTTP `Range` header: bytes already received aren't
received a second time. The progress bar picks up from the offset reached, not from
zero.

To deliberately start over from scratch, `--force` ignores both the existing archive and
the `.part`.

## The checksum

`sha256` is used to detect that an archive has changed — meaning its contents will need
to be re-analyzed.

It is computed **as the transfer streams by**, which is free: the bytes pass through
memory anyway. But after a resumption, part of the file hasn't gone through the
computation, and a full pass over thirty-five gigabytes takes several minutes.
`glyphwell` therefore doesn't trigger it on its own: the checksum is then displayed as
`not computed`, and `--hash` forces it.

## Traceability

Each acquisition leaves a row in the `corpus_downloads` table, written as `pending`
**before** the transfer — a missing database should fail the command right away, not
after thirty-five gigabytes.

```bash
sqlite3 data/glyphwell.db \
  "SELECT opus_version, language, status, downloaded_at FROM corpus_downloads"
```

| Column | Content |
|---|---|
| `status` | `pending` \| `downloaded` \| `failed` |
| `url` | exact URL served by the OPUS index |
| `archive_path` | local location of the archive |
| `sha256` | checksum, if it could be computed |
| `downloaded_at` | end of the transfer |
| `verified_at` | opening of the archive and counting of members |

A checksum already known is never erased by a later run that doesn't produce one. There
is no `extracted` status: nothing is extracted.

## Rerunning the command

`corpus fetch` is idempotent. Rerun on an archive that's already present, it doesn't
re-download anything, re-verifies the archive, and updates traceability. It's the
simplest way to check that the corpus is in good shape.

## Troubleshooting

**"no monolingual archive … in the OPUS index"** — the corpus / version / language
combination doesn't exist. The message lists the releases and languages the index
actually offers; this is most often a release that doesn't exist for that language.

**"OPUS index unreachable"** — the index (`https://opus.nlpl.eu/opusapi`) didn't respond.
Behind a corporate proxy, set `HTTPS_PROXY`. Nothing was downloaded, nothing needs
cleaning up.

**"download interrupted … the file … is kept"** — the interruption occurred during the
transfer. Rerun the same command: it will resume.

**"… is not a usable zip archive"** — the file present is truncated or corrupted.
`--force` replaces it.

**Disk full** — the write error names the `.part` file in question. Free up space or move
the destination (`--dest`, or `GLYPHWELL_DATA_DIR`), then rerun: what has already been
downloaded is kept.

## What's next

The archive is in place, but its content is not yet cataloged: run `glyphwell corpus
index` to walk its members and populate the `subtitle_files` table, then move on to
[search.md](search.md) to define and run a search.
