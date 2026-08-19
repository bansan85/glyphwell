# ADR-0004: Define a search with a hashed YAML manifest

**Status**: Accepted
**Date**: 2026-08-24

## Context

A search needs a prompt, a model, selection filters over the corpus, a chunking
configuration and an expected output shape. That definition has to be reusable, and it has
to be tied to the results it produced: editing a prompt and then appending to the previous
results would silently mix answers from two different questions.

## Decision Drivers

- Must be identifiable, so that changing the definition is detectable.
- Must be validatable before a long run starts, not part-way through.
- Should be diffable and reviewable.
- Should not require executing arbitrary code to read a search definition.

## Considered Options

### Option 1: Declarative YAML manifest, hashed

- **Pros**: Reviewable and versionable; validated up front by a pydantic model; hashing the
  file gives a stable identity; no code execution.
- **Cons**: Anything the schema does not express cannot be expressed at all.

### Option 2: Python plugin per search

- **Pros**: Arbitrary logic in pre-filtering and post-processing.
- **Cons**: No meaningful identity to hash, since behaviour depends on imported code;
  executes arbitrary code; harder to review.

### Option 3: Plain prompt file plus CLI options

- **Pros**: Minimal.
- **Cons**: Model, filters and chunking end up in shell history rather than in a reviewable
  artefact, so a run cannot be reproduced from a file.

## Decision

A search is a **YAML manifest**, validated by a pydantic v2 model, identified by the
**SHA-256 of its normalised content**. The manifest carries `model`, `options`, `select`,
`chunk`, `prefilter`, `prompt`, `output` and `match_when`. The full YAML is copied into
`runs.manifest_snapshot` when a run starts.

## Rationale

Hashing is what makes the resume design of ADR-0005 safe across edits: a changed manifest
produces a different hash and therefore a new run, instead of appending answers from a new
prompt to results produced by the old one. That property is unavailable with a Python
plugin, whose behaviour is not captured by hashing a file.

Snapshotting the YAML into the run keeps a completed run interpretable after the source file
is edited or deleted.

The hash is computed over normalised content so that a checkout with different line endings
does not change a run's identity.

## Consequences

### Positive

- Editing a manifest starts a new run rather than corrupting an existing one.
- A run stays readable without its source file.
- Manifests are reviewable and carry no executable code.

### Negative

- Every new capability has to be added to the schema; there is no escape hatch for one-off
  logic.
- Cosmetic edits, such as reformatting or a comment change, also change the hash and so
  start a new run.

### Risks

- Excessive rigidity in the schema. Bounded by the pattern pre-filter, which covers the
  common case that would otherwise need code, and by the fact that the schema can grow
  without invalidating the design.

## Related

- `manifest/model.py`, `manifest/loader.py`, `manifest/prefilter.py`, `searches/example.yaml`.
- ADR-0002 (why the pre-filter exists), ADR-0005 (what the hash protects).
