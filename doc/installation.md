# Installation

## Prerequisites

- **Python 3.12** or more recent.
- **[`uv`](https://docs.astral.sh/uv/)** — everything goes through it. Never install a
  package with `pip` into `.venv`: `uv.lock` and the environment would silently drift apart.
- **Ollama** — only for the search step, not for fetching the corpus.

## Setup

```bash
pip install uv          # once, if uv isn't already present
git clone <repository> glyphwell && cd glyphwell
uv sync --all-extras    # creates the venv, resolves and installs everything
uv run glyphwell --help
```

`uv sync` creates `.venv/` and installs the project in editable mode. All project
commands are then invoked via `uv run glyphwell …`.

## Disk space

This is the only real sizing consideration in the project.

| Item | Size |
|---|---|
| OpenSubtitles archive `en` / `raw`, release `v2024` | 35.8 GB |
| SQLite database after indexing | a few hundred MB |
| IMDb datasets (`.tsv.gz` + import) | ~1 GB |

The archive **is not extracted**: plan for its size, not double. See
[corpus.md](corpus.md#why-the-archive-is-never-extracted).

The working directory is chosen via `GLYPHWELL_DATA_DIR` — copy `.env.example` to
`.env` and adjust it, or pass `--data-dir` to each command. Everything it contains is
reconstructible: it is ignored by git and can be deleted without losing anything but
download time.

## Verifying the installation

```bash
uv run glyphwell --version
uv run glyphwell db init
uv run glyphwell db status
```

To validate the whole acquisition chain without committing to tens of gigabytes, use a
small OPUS corpus — a few seconds is enough:

```bash
uv run glyphwell corpus fetch --corpus Books --language en --version latest
```

## Development

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pre-commit install
```

The project is typed end to end, checked by mypy in very strict mode. Conventions
and design decisions are recorded in [CLAUDE.md](../CLAUDE.md).
