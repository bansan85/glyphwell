# glyphwell

LLM-driven search across the entire OpenSubtitles subtitle corpus.

`glyphwell` chains four steps:

1. **Download** the subtitles — OPUS *OpenSubtitles* corpus, language `en`, format `raw`
   (non-tokenized XML), via [`opustools`](https://pypi.org/project/opustools/). The archive
   is never extracted: subtitles are read from it on the fly.
2. **Resolve titles** — subtitles are classified by IMDb identifier, and the official
   IMDb datasets join directly on that identifier: title, type (movie / series /
   episode), year, adult flag, episode → series relationship. Offline, no API key.
3. **Search** — a YAML manifest describes the prompt, the Ollama model, the selection
   filters, and the expected output schema. Each subtitle is split into sliding chunks
   of N sentences; each chunk yields one call to the model.
4. **Resume** — state is persisted in SQLite at chunk granularity: an interrupted search
   resumes at the current line, not at the start of the file. A subtitle whose content
   changes (new OPUS release) has only its own results invalidated.

## Installation

```bash
pip install uv          # once, if uv isn't already present
uv sync --all-extras    # creates the venv, resolves and installs everything
```

Copy `.env.example` to `.env` and adjust `GLYPHWELL_DATA_DIR`: the full English archive
weighs **35.8 GB** for the `v2024` release.

## Quick start

Two commands are enough to fetch the corpus:

```bash
uv run glyphwell db init                      # creates the database
uv run glyphwell corpus fetch --language en   # downloads the OpenSubtitles archive
```

`fetch` announces the URL and size before committing to anything, then displays the
volume, throughput, and remaining time:

```
OPUS archive: https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2024/raw/en.zip
Release v2024, language en, preprocessing raw — about 35.8 GB
Destination: data\corpus
downloading ━━━━━━━━━━━━━━━━━━ 4.2/35.8 GB 18.4 MB/s 0:28:31
```

Interrupted partway through? Rerun the same command: the download resumes at the byte
where it left off. On arrival, the archive is opened and its contents summarized —
without ever being extracted:

```
 Archive              data\corpus\OpenSubtitles_v2024_raw_en.zip
 Size                 35.8 GB
 Checksum             83279cfd5aab4bfcc54654134e35c5846027241b7a72f01774f102a815797d5c
 Subtitles            …
 Service files        3
Internal layout:
  OpenSubtitles/raw/en/2022/1596342/1957893755.xml
  …
```

To validate the whole chain in seconds rather than hours, first try it on a small OPUS
corpus:

```bash
uv run glyphwell corpus fetch --corpus Books --language en --version latest
```

## Commands

All commands go through `uv run`.

```bash
# Database
uv run glyphwell db init                  # creates the schema
uv run glyphwell db status                # schema version + counters
uv run glyphwell db vacuum

# Subtitle corpus
uv run glyphwell corpus fetch --language en          # OPUS download
uv run glyphwell corpus index                        # archive scan -> SQLite
uv run glyphwell corpus refresh                      # re-hash + targeted invalidation

# Title metadata
uv run glyphwell metadata fetch-imdb                 # official IMDb datasets
uv run glyphwell metadata import-imdb                # import into SQLite

# Search
uv run glyphwell search run searches/example.yaml
uv run glyphwell search status
uv run glyphwell search resume 1
uv run glyphwell search export 1 --format jsonl
```

## Writing a search

A YAML manifest, version-controllable and hashed — any change to the file creates a new
search instead of reusing stale results. See
[`searches/example.yaml`](searches/example.yaml), fully commented.

## Documentation

Detailed documentation lives in [`doc/`](doc/index.md):

- [installation.md](doc/installation.md) — `uv`, prerequisites, disk space
- [configuration.md](doc/configuration.md) — `GLYPHWELL_*` variables, `data/` layout
- [corpus.md](doc/corpus.md) — step 1 in detail: releases, resumption, internal
  layout of the archive, traceability, troubleshooting

## Development

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit install
```

The project is typed end to end and checked by mypy in very strict mode
(`strict` + `disallow_any_explicit` + `disallow_any_unimported`). Conventions
are detailed in [CLAUDE.md](CLAUDE.md).

## Status

The skeleton is in place — packaging, SQLite schema, CLI, manifest loading, quality
tooling — and **step 1 is operational**: `glyphwell corpus fetch` downloads, resumes,
verifies, and tracks the OpenSubtitles archive.

The rest of the business logic (archive indexing, IMDb dataset import, search engine)
is present in the form of typed stubs — see the "Current scope" section of
[CLAUDE.md](CLAUDE.md).
