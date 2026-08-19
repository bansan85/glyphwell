# ADR-0007: Enforce very strict typing with no escape hatches

**Status**: Accepted
**Date**: 2026-08-24

## Context

`glyphwell` spends most of its work at untyped boundaries: YAML manifests, gzipped TSV
datasets, XML that is not always well-formed, and JSON returned by a local model. These are
exactly the places where a wrong assumption about a value surfaces late, after a long run,
rather than at the point where the assumption was made.

A typing policy had to be set before the modules were written, because retrofitting strict
typing costs far more than starting with it.

## Decision Drivers

- Must catch shape errors at the boundary, not deep inside a long-running search.
- Must keep the strictness verifiable, so that it cannot erode quietly over time.
- Should stay uniform, so there is no per-module negotiation about what is checked.

## Considered Options

### Option 1: mypy `strict` plus additional restrictions, applied uniformly

- **Pros**: Untyped values cannot enter the code without an explicit, reviewable narrowing
  step; the configuration is one block in `pyproject.toml`; every suppression must name the
  error code it suppresses, and unused suppressions are reported.
- **Cons**: Untyped third-party libraries require local stubs; boundary code has to be
  written as `object` followed by narrowing, which is more verbose than annotating `Any`.

### Option 2: mypy `strict` with per-module relaxations

- **Pros**: Awkward modules can be exempted immediately.
- **Cons**: The exemption list is where strictness goes to die; each entry needs its own
  justification, and none of them get revisited.

### Option 3: Type hints without enforcement

- **Pros**: No friction.
- **Cons**: Annotations drift out of agreement with the code and become misleading, which is
  worse than having none.

## Decision

Run mypy with `strict = true` plus `warn_unreachable`, `disallow_any_explicit`,
`disallow_any_unimported`, `disallow_any_decorated`, and an extended `enable_error_code`
list. The configuration applies uniformly to `src` and `tests`, with **no**
`[[tool.mypy.overrides]]` section.

Consequences that follow directly, and are load-bearing:

- `Any` cannot be written as an annotation. Untyped boundaries are annotated `object` and
  narrowed immediately, by pydantic validation or by explicit checks. JSON payloads use
  `JsonValue` and `JsonObject`, re-exported from pydantic in `types.py`.
- `disallow_any_unimported` rules out `ignore_missing_imports`. An untyped dependency needs
  a local stub under `stubs/`, declaring only the surface actually used. `opustools` is the
  current case.
- No bare suppressions: `ignore-without-code` forces `# type: ignore[code]`, and
  `warn_unused_ignores` removes suppressions once they stop being needed.

The style rules that go with it are recorded in `CLAUDE.md`: native unions, builtin
generics, `collections.abc` abstractions, PEP 695 aliases, frozen slotted dataclasses for
value objects, `Protocol` for interfaces, `StrEnum` with `assert_never` for closed statuses,
`pathlib.Path` throughout, and generators for anything corpus-sized.

## Rationale

The strictness is not aesthetic. The failure mode this project is exposed to is a malformed
or unexpected value from an external source propagating silently until it corrupts a run
that took hours. Banning `Any` forces every such value through a narrowing step that is
visible in review.

Refusing per-module overrides is the part that makes the rest hold. An override list starts
as a pragmatic concession and becomes the permanent shape of the codebase, because nothing
ever forces a revisit.

## Consequences

### Positive

- External data is validated where it enters, by construction rather than by discipline.
- Stubs are complete enough to typecheck before any implementation exists, so the module
  boundaries are settled before the bodies are written.
- Suppressions are self-documenting and self-expiring.

### Negative

- Every untyped dependency costs a hand-written stub.
- Boundary code is more verbose than it would be with `Any`.
- Two pitfalls had to be worked around and are documented in `CLAUDE.md`: Typer cannot
  unwrap a PEP 695 `TypeAliasType` at runtime, so `LogLevel` is an implicit alias; and the
  pydantic mypy plugin with `init_typed = true` rejects `Settings(**overrides)`, so settings
  are constructed with explicit keywords.

### Risks

- A future dependency that cannot be stubbed reasonably. If an override becomes
  unavoidable, it must be scoped to the single module concerned and explained in
  `CLAUDE.md`, never applied globally.

## Related

- The `[tool.mypy]` section of `pyproject.toml`, `types.py`,
  `stubs/opustools/__init__.pyi`.
- ADR-0001 (same file holds the configuration), ADR-0004 (pydantic validation at the
  manifest boundary).
