# Configuration

Everything is configured via environment variables prefixed `GLYPHWELL_`, also read from
a `.env` file at the root of the repository. Each one has a usable default value:
`glyphwell` works without any configuration.

Copy the template then adjust it:

```bash
cp .env.example .env
```

## Variables

| Variable | Default | Role |
|---|---|---|
| `GLYPHWELL_DATA_DIR` | `./data` | Root of all produced data. |
| `GLYPHWELL_DATABASE` | `<data_dir>/glyphwell.db` | Path to the SQLite database. |
| `GLYPHWELL_OPUS_CORPUS` | `OpenSubtitles` | Targeted OPUS corpus. |
| `GLYPHWELL_OPUS_VERSION` | `v2024` | OPUS release — the most recent. |
| `GLYPHWELL_OPUS_LANGUAGE` | `en` | Corpus language. |
| `GLYPHWELL_OLLAMA_HOST` | `http://localhost:11434` | Ollama server. |
| `GLYPHWELL_OLLAMA_TIMEOUT` | `300` | Timeout for a model call, in seconds. |
| `GLYPHWELL_CONCURRENCY` | `4` | Chunks analyzed in parallel (1 to 64). |
| `GLYPHWELL_LOG_LEVEL` | `INFO` | `DEBUG` \| `INFO` \| `WARNING` \| `ERROR`. |

Three of them have a command-line equivalent, which takes precedence over the
environment:

```bash
uv run glyphwell --data-dir /mnt/gros-disque/glyphwell --log-level DEBUG corpus fetch
```

## Why English by default

`en` is the language best covered by OpenSubtitles, by far. The choice can be changed via
`GLYPHWELL_OPUS_LANGUAGE` or `--language`, but any other language yields a noticeably
smaller corpus.

## `data/` layout

```
data/
├── corpus/                             OPUS archive — one zip per (release, language)
│   └── OpenSubtitles_v2024_raw_en.zip
├── downloads/                          IMDb dataset TSVs
├── exports/                            results of `search export`
└── glyphwell.db                        search catalog and progress
```

`data/corpus/` contains an **archive**, not a directory tree of subtitles: it is never
extracted (see [corpus.md](corpus.md)). During a download, a `*.zip.part` file is
temporarily added there; it holds what has already been received and enables resumption.

All of `data/` is ignored by git and fully reconstructible: deleting it only costs the
time to re-download.

## What the database contains

SQLite, **deliberately without FTS5**: subtitle text is neither copied nor indexed in the
database. The archive remains the sole source of the text; the database carries only the
catalog and progress state.

| Table | Role |
|---|---|
| `titles` | IMDb titles: type, title, year, episode → series relationship. |
| `subtitle_files` | An archive member: name, imdb_id, checksum, OPUS release. |
| `runs` | A search: manifest, its hash, its snapshot, model, status. |
| `run_files` | Work queue and **resume point** per file. |
| `results` | One model response per chunk, with its sentence range. |
| `corpus_downloads` | Traceability of OPUS downloads. |
| `imports` | Traceability of IMDb dataset imports. |

The schema carries its version in `PRAGMA user_version`. `glyphwell db init` is
idempotent and can be rerun safely.
