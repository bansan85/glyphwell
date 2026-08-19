# ADR-0001: Use uv for packaging and dependency management

**Status**: Accepted
**Date**: 2026-08-24

## Context

The project started from an empty repository containing only a `.venv` (Python 3.12.3) with
`pip` installed. A tool had to be chosen before any dependency could be declared.

The workload matters here: `glyphwell` pulls in `opustools`, `lxml`, `pydantic`, `httpx`,
`typer` and `ollama`, and the dependency graph is resolved repeatedly during development.

## Decision Drivers

- Must produce a reproducible environment, so a lock file is required.
- Must declare metadata in the PEP 621 `[project]` table rather than a tool-specific one.
- Should keep resolution fast enough not to interrupt the work.
- Should not require a second tool to manage the interpreter.

## Considered Options

### Option 1: uv

- **Pros**: Rust implementation, resolution roughly one to two orders of magnitude faster
  than the Python-based tools; native PEP 621; any PEP 517 backend; installs interpreters
  itself; `uv pip` works as a drop-in replacement.
- **Cons**: Young (2024), so a smaller body of documentation and fewer plugins.

### Option 2: Poetry

- **Pros**: Established since 2018, mature plugin ecosystem, widely documented.
- **Cons**: Slow resolution on large graphs; PEP 621 support only from Poetry 2.0, the
  historic `[tool.poetry]` table still being common in examples; does not install
  interpreters.

### Option 3: pip with pyproject.toml only

- **Pros**: Nothing extra to install; the existing `.venv` is usable immediately.
- **Cons**: No strict lock file, so no reproducibility guarantee.

## Decision

Use **uv**, with `pyproject.toml` (PEP 621), `uv.lock`, the `hatchling` build backend and a
`src/` layout. Every project command goes through `uv run`.

## Rationale

uv satisfies every driver at once, and the reproducibility requirement rules out plain pip.
Against Poetry the deciding factors were resolution speed and standards conformance: the
`[project]` table keeps the manifest portable if the tool is ever replaced, which is the
cheapest available hedge against uv's relative youth.

## Consequences

### Positive

- `uv sync --all-extras` is the single command that establishes the environment.
- `uv.lock` is committed, so a clone reproduces the exact dependency set.
- The interpreter is managed by the same tool as the dependencies.

### Negative

- uv must be installed once before anything else works.
- Mixing `pip install` into the managed `.venv` desynchronises it from `uv.lock`. This is
  recorded as a rule in `CLAUDE.md`.

### Risks

- A young tool could change its interface. Bounded by keeping all metadata in the standard
  `[project]` table: switching to another PEP 621 tool would cost only the lock file.

## Related

- `pyproject.toml`, and the commands section of `CLAUDE.md`.
- ADR-0007, which relies on the same file for the mypy and ruff configuration.
