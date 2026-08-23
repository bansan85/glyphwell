# ADR-0013: Re-validate the model's JSON output client-side

**Status**: Accepted
**Date**: 2026-08-25

## Context

A manifest's `output.schema` is passed to Ollama's `format` parameter to constrain
generation. Whether that constraint is honored exactly depends on the model and its
quantization: it reduces the rate of malformed output, it is not a server-side contract
the caller can skip validating. `glyphwell` also deliberately targets community
"uncensored" fine-tunes for prompts a more conservative instruct model would refuse — a
category of model that is not benchmarked or selected for schema compliance the way an
official instruct release is.

## Decision Drivers

- Must not let a run store a result that only looks like it matches the manifest's
  schema.
- Must give a clear, attributable error when a chunk's output cannot be trusted, instead
  of storing it anyway.
- Should keep the *policy* of which schema to request (a `glyphwell.manifest` concern)
  separate from the *transport* of the call (`glyphwell.ollama`), so the client stays
  reusable without depending on manifest types.

## Considered Options

### Option 1: Trust `format` alone

- **Pros**: one fewer validation pass; a simpler `OllamaClient.complete`.
- **Cons**: a schema-constrained response is only as reliable as the model applying the
  constraint; nothing catches a response that violates `additionalProperties: false`, has
  a wrong type, or drops a required field beyond what the server itself enforces — which
  varies by model.

### Option 2: Constrain generation and re-check client-side (chosen)

- **Pros**: `format` still does most of the work, cutting the *rate* of malformed
  responses; `glyphwell.search.results.validate_output` then checks the decoded payload
  against the manifest's actual schema and resolves `match_when` independently of what the
  server claims to have produced.
- **Cons**: one extra parse-and-validate pass per chunk — negligible next to the cost of
  the model call itself.

## Decision

`OllamaClient.complete` decodes the response as JSON when a schema was requested — a
syntactic check, "is this parseable JSON shaped like an object at all" — and raises
`ModelOutputError` if not. `glyphwell.search.results.validate_output` then re-checks the
decoded payload against the manifest's schema and resolves `match_when`, entirely
independently of the `format` constraint that was requested. The two checks live in
different modules on purpose: `glyphwell.ollama` stays decoupled from `glyphwell.manifest`,
so the client has no notion of schemas beyond "one was requested or not."

## Rationale

`format` lowers the probability of a malformed response; it is not a substitute for
validating what actually came back — particularly given the project's own choice to
target less-aligned, community fine-tuned models where following a JSON schema is not
what the fine-tune was optimized for. Layering syntactic decoding in `glyphwell.ollama`
and semantic/schema validation in `glyphwell.search.results` keeps the transport module
honest about what it actually guarantees, and keeps "what a match means for this
manifest" where the manifest's own types already live.

## Consequences

### Positive

- A run cannot silently store a result that violates its own manifest's schema.
- Swapping models — including to a less schema-reliable uncensored one — changes only the
  *rate* of `ModelOutputError`s, never the correctness of what gets committed.
- `glyphwell.ollama` has no dependency on `glyphwell.manifest`, so the client stays
  testable and reusable on its own.

### Negative

- Every chunk pays two passes over the response (JSON decode, then schema validation)
  instead of one.
- A model that violates the schema despite the constraint costs a chunk outright
  (`ModelOutputError`, surfaced per file via `run_files.mark_error`), rather than being
  coerced into a best-effort shape.

### Risks

- A model with a high schema-violation rate turns a search into a high per-file error
  rate rather than a slow-but-complete run. `ensure_model` fails a run before it starts
  scanning the corpus if the model is missing, but nothing today measures a model's
  schema-compliance rate before committing to a long run — worth reconsidering if an
  uncensored model turns out to violate the schema often enough to matter in practice.

## Related

- `ollama/client.py`, `search/results.py`, `search/engine.py` (`_complete_chunk`,
  `_commit_completion`).
- ADR-0004 (the manifest field this schema comes from).
