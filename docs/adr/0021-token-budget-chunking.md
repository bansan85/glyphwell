# ADR-0021: Size chunks from a token budget, not a fixed sentence count

**Status**: Accepted
**Date**: 2026-08-27

## Context

ADR-0005 cut a subtitle into sliding windows of `chunk.size` sentences with
`chunk.overlap` overlap. `chunk.size` and `options.num_ctx` (the model's context window,
in tokens) were two independent manifest fields that had to be kept in sync by hand:
`searches/example.yaml` carried a comment warning that `num_ctx` must stay larger than
the rendered chunk or Ollama silently truncates the context — nothing enforced or
computed that relationship. A chunk of `chunk.size` short sentences wastes context a
larger window could have used; a `chunk.size` tuned for long sentences overflows
`num_ctx` on a file of short ones.

## Decision Drivers

- The number of sentences per chunk must adapt to how long each sentence actually is,
  instead of being a single fixed count applied to every file.
- It must adapt to `options.num_ctx`/`options.num_predict` automatically, so the two can
  no longer drift out of sync.
- Must stay deterministic per manifest: `Chunk.index` must keep designating the same
  sentence range on every pass over a given file, or the `UNIQUE(run_id, file_id,
  chunk_index)` idempotency guarantee (ADR-0005) breaks.
- No exact per-model tokenizer is available: Ollama serves many model families, each with
  its own tokenizer, and none is known ahead of a call.

## Considered Options

### Option 1: Token-budget bin-packing, heuristic character-based token estimate

- **Pros**: No new dependency; adapts to both sentence length and `num_ctx`/`num_predict`
  automatically; stays deterministic per manifest, since both options are already part of
  the manifest hash.
- **Cons**: The estimate is approximate, not exact — mitigated by a safety margin and by
  deliberately biasing the estimate high (fewer characters assumed per token) rather than
  risking silent truncation.

### Option 2: Add a tokenizer dependency (e.g. `tiktoken`)

- **Pros**: Exact token counts for the tokenizer it implements.
- **Cons**: `tiktoken` (and similar libraries) encode OpenAI's own tokenizers, not the
  tokenizer of whichever model a manifest names — Ollama hosts many model families
  (Llama, Qwen, Mistral, ...), each with a different one. An exact count for the wrong
  tokenizer is not more correct than a heuristic; it is only more confident.

### Option 3: Keep `chunk.size`, just validate it against `num_ctx` at load time

- **Pros**: Smallest change; keeps today's explicit, easy-to-reason-about sentence count.
- **Cons**: Does not solve the actual problem — a fixed sentence count still wastes
  context on short sentences and can still overflow on long ones, since "sentence count"
  and "token count" are not the same axis. Validation would only catch the case where the
  *average* sentence length happens to overflow, not a single long-sentence file.

## Decision

`chunk.size` is removed from the manifest. `corpus/chunker.py::iter_chunks` fills each
chunk with as many sentences as fit under a `token_budget`, computed once per file by
`glyphwell.tokens.chunk_token_budget`:

```
margin        = ceil(0.15 * num_ctx)
ceiling       = num_ctx - num_predict - estimate_tokens(prompt overhead) - margin
token_budget  = min(ceiling, num_predict)
```

`estimate_tokens` is `ceil(len(text) / 3.2)` — a conservative characters-per-token ratio
for English dialogue text. "Prompt overhead" is `prompt.system` and `prompt.user`
rendered with an empty chunk (`ollama.prompts::render_overhead`), so the estimate accounts
for the static instructions and JSON-schema request surrounding every chunk, not just the
chunk's own sentences. The 15% margin is a ratio of `num_ctx`, not a flat token count, so
it scales with the context window instead of being too tight at a small `num_ctx` or
wastefully large at a big one.

`token_budget` is bounded by two independent constraints, not `ceiling` alone. A first
version of this design used `ceiling` directly, and failed on the very first real run: for
`searches/example.yaml`'s `num_ctx: 24576`/`num_predict: 1024`, `ceiling` alone came out to
~18,700 tokens — around 1,800+ sentences in one chunk, an entire episode in the worst case.
The model, faced with that much dialogue and a schema that reports one JSON object per
finding, had far more to say than `num_predict: 1024` allowed, and Ollama cut the response
off mid-string once it hit that limit — a call that took over 5 minutes and still ended in
`model response is not valid JSON`. `ceiling` only guarantees the *prompt* fits in
`num_ctx`; it says nothing about whether the *response* fits in `num_predict`, which is
what actually failed here. Capping `token_budget` at `num_predict` keeps the chunk from
growing far past what the response budget can describe, restoring roughly the same
input-to-output ratio `searches/example.yaml`'s previous hand-tuned `chunk.size: 150`
(≈1,000-1,200 tokens) already had against its `num_predict: 1024` — see *Rationale*.

`options.num_ctx` and `options.num_predict` become **required**, positive-integer
manifest fields (`SearchManifest._check_context_options`) — chunk sizing now depends on
both, so neither can be silently absent; a manifest missing either fails validation before
the first file is scanned, consistent with how every other manifest error is reported.

`chunk.overlap` (sentences repeated between one chunk and the next) is unchanged in unit
and meaning — still a plain sentence count, not converted to a token count. It keeps
`search/checkpoint.py::resume_position`'s arithmetic exactly as it was: that function
already computed the resume position from `overlap` alone (the `size` parameter had
already become vestigial there, cancelling out algebraically — see ADR-0005's
implementation), so token-budget sizing needed no change to resume math at all.

## Rationale

Option 2 was rejected because "exact" is not meaningful when the tokenizer being counted
against is not the one the request will actually use — a wrong-but-precise count is worse
than an approximate one that is honestly labeled as such. Option 3 doesn't address the
actual mismatch (sentence count vs. token count are different units); it only catches the
symptom in the average case.

`iter_chunks` cuts a chunk *before* adding a sentence that would overflow the budget,
rather than after, so a chunk's total (barring the single-oversized-sentence case below)
never exceeds `token_budget` — the greedy sliding-window shape of ADR-0005 is otherwise
unchanged, just re-triggered by a running token sum instead of a running count. A single
sentence whose own estimate exceeds the budget is still emitted alone: the sentence is the
indivisible unit of a chunk (as it always was), so this is the best the function can do:
it logs a warning so an operator can notice a pathological line (e.g. an unbroken lyrics
block) rather than failing the whole search.

There is no way to know, in general, how many response tokens a given amount of input
content will need — that ratio is entirely a function of the prompt and output schema a
manifest author writes, not something glyphwell can infer. Capping at exactly `1×
num_predict` is therefore a heuristic, not a derived quantity, but it is the simplest one
that is both safe by default (a chunk can never outgrow the response budget meant to
describe it) and cheaply escapable: a manifest whose schema is small and does not scale
with input (a lone boolean, say) is free to ask for denser chunks by raising `num_predict`
past what a single response actually needs — one existing, already-required knob, not a
new one. The alternative of inventing a multiplier (`num_predict × 2`, `× 4`, ...) would
only trade one unjustified constant for another, with no data to justify a specific value
over `1×` — and `1×` is the one directly evidenced by `searches/example.yaml`'s own prior,
manually-tuned `chunk.size: 150` (≈1,000-1,200 tokens against `num_predict: 1024`).

## Consequences

### Positive

- `chunk.size`/`num_ctx` can no longer silently drift apart: chunk sizing is a function
  of `num_ctx` and `num_predict`, so raising either automatically produces bigger chunks
  on the very next file.
- Short-sentence files get denser chunks (fewer model calls per file) and long-sentence
  files stay within budget automatically, instead of both being forced through one
  hand-tuned constant.
- `--dry-run` now prints the computed token budget, making the automatic sizing
  inspectable without reading code.
- A chunk can never dwarf `num_predict`, so a task whose response scales with its input
  (an array of findings, one per interesting line) no longer risks the model running out
  of response budget mid-answer — the exact failure this ADR's `num_predict` cap was
  added to close (see *Decision*).

### Negative

- The token estimate is approximate: a model whose actual tokenizer is far denser than
  the 3.2-characters-per-token heuristic (e.g. heavy use of non-Latin scripts, which this
  project does not target — the corpus is English-only, see CLAUDE.md §1) could still
  overflow `num_ctx` despite the safety margin. The margin is deliberately generous
  (15% of `num_ctx`) to make this unlikely for the project's actual (English subtitle)
  workload.
- `chunk_count` (a closed-form "chunk count from sentence count alone" helper, used only
  by its own tests) is removed: it cannot be reimplemented without reading every
  sentence's text, since chunk boundaries no longer depend on sentence count alone.
- A manifest whose task genuinely does not need much response per chunk (a lone
  `matched` boolean, say) gets chunks no denser than `num_predict` tokens' worth of
  content even though its actual response would have fit a much larger chunk — the price
  of a safe-by-default cap with no per-task knowledge. The escape hatch is raising
  `num_predict` (see *Rationale*), which is slightly wasteful of the reserved response
  budget but not incorrect.

### Risks

- A manifest whose `num_ctx` cannot cover `num_predict` plus its own prompt overhead plus
  the margin fails loudly (`ManifestError`) on the first file, not at manifest-load time —
  title text length is file-dependent, so the exact overhead can't be known until then.
  In practice this only happens when the manifest is misconfigured to begin with (an
  `num_ctx` too small for the prompt itself), so the failure mode is a clear, early error
  rather than silent truncation.
- Changing `options.num_ctx`, `options.num_predict`, or the prompt templates now
  re-partitions a file exactly as changing `chunk.size` used to — already contained by
  ADR-0004: all three are part of the manifest, so changing any of them changes the
  manifest hash and starts a new run.

## Related

- `glyphwell/tokens.py`, `corpus/chunker.py`, `ollama/prompts.py::render_overhead`,
  `manifest/model.py::SearchManifest._check_context_options`.
- ADR-0005 (sliding-window chunking and resume — amended by this ADR: the window shape is
  unchanged, only how its width is determined), ADR-0004 (manifest hash).
