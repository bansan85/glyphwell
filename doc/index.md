# glyphwell documentation

`glyphwell` searches the entirety of the OpenSubtitles subtitles using an LLM run
locally by Ollama.

## Contents

| Document | Contents |
|---|---|
| [installation.md](installation.md) | Install `uv`, the environment, and size the disk. |
| [configuration.md](configuration.md) | `GLYPHWELL_*` variables, `data/` layout. |
| [corpus.md](corpus.md) | **Step 1**: fetch the OpenSubtitles archive and read it. |
| [metadata.md](metadata.md) | **Step 2**: fetch and import the IMDb datasets, resolve titles. |
| [search.md](search.md) | **Step 3**: catalogue the corpus and search it with a manifest. |

## The four-step pipeline

1. **Download the corpus.** The OPUS *OpenSubtitles* archive (language `en`, format `raw`)
   is dropped onto disk as-is. It is never extracted: subtitles are read from it on the
   fly. → [corpus.md](corpus.md)
2. **Resolve titles.** Subtitles are classified by IMDb identifier; the official IMDb
   datasets join directly on it and give the title, the type (movie / series / episode),
   the year, and the episode → series relationship. Offline, no API key.
   → [metadata.md](metadata.md)
3. **Search.** A YAML manifest describes the prompt, the Ollama model, the selection
   filters, and the expected output schema. Each subtitle is split into sliding chunks
   of N sentences; each chunk yields one call to the model. → [search.md](search.md)
4. **Resume.** State is persisted in SQLite at chunk granularity: an interrupted search
   resumes at the current line, not at the start of the file.

## Progress status

Steps 1 through 3 are operational; step 4 (resuming a run) is implemented for the
resume-inside-a-file case, but `search resume`, `search status`, and `search export`
themselves are not yet wired up.

| Capability | Status |
|---|---|
| `glyphwell db init` / `status` / `vacuum` | operational |
| `glyphwell corpus fetch` | **operational** |
| `glyphwell corpus index` | **operational** |
| `glyphwell metadata fetch-imdb` / `import-imdb` | **operational** |
| `glyphwell search run` (including `--dry-run`) | **operational** |
| `glyphwell search resume` / `status` / `export` | to implement |

Commands not yet implemented are wired into the CLI and already expose their help: their
signature is settled, only the processing is missing.

## Two principles that run through the project

**Nothing is extracted.** The corpus archive stays a single zip file. This saves about
forty gigabytes and hundreds of thousands of files, and yields an artifact that can be
verified with a single checksum.

**Nothing is lost on interruption.** The download resumes where it left off; search will
resume in the middle of a subtitle. A `Ctrl-C` is never costly.
