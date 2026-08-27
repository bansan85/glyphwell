# ADR-0022: Calibrate the response ratio from a run's own observed completions

**Status**: Accepted
**Date**: 2026-08-27

## Context

ADR-0021 sizes a chunk against two independent constraints: the context ceiling
(`num_ctx` minus `num_predict`, prompt overhead, and a safety margin), and a
response-safety cap of `1x num_predict` — the assumption that a chunk should never be
larger, in estimated tokens, than the response budget meant to describe it. That `1x`
ratio was picked with no data to justify it over any other value; ADR-0021's own
Rationale section says so explicitly: "there is no way to know, in general, how many
response tokens a given amount of input content will need... capping at exactly `1x
num_predict` is therefore a heuristic, not a derived quantity."

Real runs of `searches/example.yaml` (`num_ctx: 24576`, `num_predict: 1024`) now provide
that missing data. Debug-log token summaries (`search/engine.py::_token_summary`) across
a live search consistently showed:

- Non-matching chunks (the common case for this manifest): completion 75-172 / 1024
  tokens (7-17% of `num_predict`).
- The densest matching chunk observed: completion 384 / 1024 tokens (38%).
- Prompt usage stayed at 8-9% of `num_ctx` throughout — nowhere near the context
  ceiling.

The `1x` ratio was therefore roughly 3-13x more conservative than this manifest's task
actually needed: `concealment_methods`'s response (a `matched` boolean plus at most a
handful of findings) does not scale anywhere near proportionally with how much dialogue
is fed into a chunk, unlike the array-per-interesting-line shape ADR-0021's `1x` cap was
designed to protect against.

## Decision Drivers

- Replace the blind `1x` constant with a value grounded in what a manifest's task
  actually produces, without asking a manifest author to hand-tune a new knob upfront —
  the same problem ADR-0021 raised against inventing a fixed multiplier (`x2`, `x4`, ...)
  applies equally to asking a human to guess one per manifest.
- Never trade the safety `1x` was added for: a chunk must still not risk mid-JSON
  truncation just because it was sized larger.
- Preserve every resume invariant of CLAUDE.md §7 — in particular, `Chunk.index` must
  keep designating the same sentence range on every pass over a given file, including
  across a process restart.
- No exact per-model tokenizer is available (ADR-0021 already established this): the
  calibration must work from the same character-based estimate `chunk_token_budget`
  already uses, not a real token count.

## Considered Options

### Option 1: Measure the ratio from a run's own early completions, then lock it

- **Pros**: Grounded in the actual manifest/model/corpus combination in play, not a
  guess; requires no new manifest field; automatically adapts per manifest instead of
  needing a universal constant that fits every task shape.
- **Cons**: A run's first stretch of chunks still pays the conservative `1x` cost before
  enough samples exist; the locked ratio is only as representative as the sample that
  produced it (see *Consequences → Risks*).

### Option 2: A fixed, smaller multiplier (e.g. `0.3x num_predict`) replacing `1x`

- **Pros**: Simplest possible change — one constant edited.
- **Cons**: Exactly the flaw ADR-0021 already rejected for the `1x` cap itself, just at a
  different value: no data justifies `0.3x` over `0.2x` or `0.5x` for an arbitrary future
  manifest. A task shaped like ADR-0021's original worry (an array scaling with input)
  would silently lose its safety margin.

### Option 3: A new manifest field for the response ratio, tuned by hand per search

- **Pros**: Explicit, inspectable in the YAML, no run-time state.
- **Cons**: Pushes the exact problem Option 2 has onto the manifest author instead of
  solving it — nothing in a fresh manifest tells anyone what ratio their task's response
  actually needs until they have already run it once and read the debug log by hand.
  Calibration automates precisely that manual step.

## Decision

`glyphwell.tokens.chunk_token_budget` gains a `response_ratio` parameter (default
`DEFAULT_RESPONSE_RATIO = 1.0`, reproducing ADR-0021's original behavior byte for byte)
that replaces the bare `num_predict` term of the response-safety cap with
`num_predict / response_ratio`. `glyphwell.search.calibration.Calibration` — new,
per-run, mutable state confined to the engine's single DB-owning thread exactly like
`search.checkpoint` — accumulates `(chunk_tokens, completion_tokens)` pairs from real
completions as a run processes them, where `chunk_tokens` is
`estimate_tokens(chunk.render())`: the same estimator unit `chunk_token_budget` already
operates in, so no conversion to a model's real tokenizer is ever needed.

Once `CALIBRATION_SAMPLE_SIZE` (50) completions with `chunk_tokens >=
CALIBRATION_MIN_CHUNK_TOKENS` (200) have been observed,
`glyphwell.tokens.calibrate_response_ratio` computes

```
locked_ratio = max(completion_tokens / chunk_tokens for qualifying samples) * (1 + CALIBRATION_MARGIN_RATIO)
```

and `Calibration` locks onto it permanently for the rest of the run. The **maximum**
observed ratio drives the result, not an average: a single denser chunk in the sample
must not be diluted away by many low-ratio ones, since undershooting is the failure mode
that produces truncation. The near-empty-chunk floor (`CALIBRATION_MIN_CHUNK_TOKENS`)
excludes a chunk too small to be representative — a 150-token completion over a 30-token
chunk (a file's last few sentences, say) is a "5.0" ratio that says nothing about how a
full-sized chunk behaves, and would otherwise dominate the max-based statistic. The
`CALIBRATION_MARGIN_RATIO` (0.5, i.e. 50% headroom over the worst sample) is the same
kind of deliberately generous margin ADR-0021 already applies to the context ceiling,
for the same reason: the calibration sample cannot prove it contains the densest chunk
the rest of the run will produce.

The locked ratio is persisted to a new `runs.calibrated_response_ratio` column
(`RUN_SCHEMA_VERSION` 1 -> 2) the moment it locks, via
`RunsRepository.set_calibrated_response_ratio`. `search/engine.py::_load_calibration`
reads it back at the start of every `start`/`resume`/`process_file` call, seeding
`Calibration.locked_ratio`: once set, in memory or in the database, it never changes
again for the run's lifetime. All three constants (`DEFAULT_RESPONSE_RATIO`,
`CALIBRATION_MIN_CHUNK_TOKENS`, `CALIBRATION_SAMPLE_SIZE`, `CALIBRATION_MARGIN_RATIO`)
live in `glyphwell/tokens.py`, each documented with what evidence should move it —
see *Related*.

## Rationale

Option 2 repeats ADR-0021's own rejected reasoning at a different value: an invented
constant, however plausible, is not more justified than the `1x` it would replace — it
is only differently wrong for whichever future manifest doesn't match the corpus that
inspired it. Option 3 pushes the same guess onto every manifest author, who has even
less basis to pick a number than the project does after a real run's own data exists.

Option 1's residual risk — a calibration sample not representative of the rest of the
run — is real but bounded, not open-ended: it is exactly the same *kind* of risk
ADR-0021's own character-based token estimate already carries and mitigates the same
way, with a deliberately generous margin instead of a false promise of exactness. It is
also observable rather than silent: `_token_summary`'s existing debug-log line already
shows how close a completion lands to `num_predict`, so an under-calibrated run leaves
the same trail an operator already knows to watch (see *Consequences → Risks*).

Locking the ratio once, rather than continuously re-calibrating, is what keeps chunk
sizing deterministic per manifest (CLAUDE.md §7): a value that could keep drifting
mid-run would make `Chunk.index` stop designating a stable sentence range across a
resume. A file whose calibration locks in mid-processing can therefore end up with
non-uniform chunk sizes (smaller before the lock, larger after) — a visible quirk in the
logs, not a correctness break: each already-committed chunk keeps its own fixed
`chunk_index`/sentence range regardless, and `resume_position` (`search/checkpoint.py`)
depends only on `overlap` and the last committed chunk, never on the historical budget
that produced it.

## Consequences

### Positive

- A manifest whose response does not scale much with its input (`concealment_methods`'s
  own measured 7-38% completion usage, say) automatically gets denser chunks — fewer
  model calls per file — without any manifest change or manual retuning.
- A manifest whose response genuinely does scale with input keeps ADR-0021's original
  safety: if the calibration sample's worst ratio is close to 1.0, `response_ratio`
  locks close to `DEFAULT_RESPONSE_RATIO` and the cap barely moves.
- No new manifest field: calibration is entirely a run-time, per-run behavior. A
  manifest's hash and reproducibility (ADR-0004) are unaffected.
- Locking is logged (`"calibrated response ratio locked at ..."`), so an operator
  watching a run sees exactly when and at what value it happened, alongside the existing
  `_token_summary` lines that already show whether it is holding up.

### Negative

- The first `CALIBRATION_SAMPLE_SIZE` qualifying completions of every run still pay the
  fully conservative `1x` cost — calibration is a run-time adaptation, not a load-time
  one. A resumed run whose calibration hadn't locked in before the interruption restarts
  accumulating from zero (in-memory samples are never persisted, only the final locked
  ratio): a minor, bounded cost, not a correctness issue, since `DEFAULT_RESPONSE_RATIO`
  is always a safe chunk size regardless of how many samples were seen before.
- A file whose calibration locks in partway through can end up with non-uniform chunk
  sizes across that one file (see *Rationale*) — cosmetic in the logs, not a defect.
- Three more constants to keep correctly tuned over time
  (`CALIBRATION_MIN_CHUNK_TOKENS`, `CALIBRATION_SAMPLE_SIZE`, `CALIBRATION_MARGIN_RATIO`),
  on top of ADR-0021's `SAFETY_MARGIN_RATIO`/`CHARS_PER_TOKEN`. Each carries its own
  retuning guidance in `glyphwell/tokens.py` specifically so this is not a guess exercise
  a future change has to redo from scratch.

### Risks

- **The calibration sample may not contain the run's densest chunk.** Bounded by
  `CALIBRATION_MARGIN_RATIO`'s 50% headroom, not eliminated: a manifest whose response
  density varies far more across the corpus than within the first `CALIBRATION_SAMPLE_SIZE`
  chunks could still under-calibrate. Mitigated by, in order: raising
  `CALIBRATION_SAMPLE_SIZE` if the queue's deterministic order (`ORDER BY rel_path`)
  makes the early stretch unrepresentative on a given corpus; watching
  `_token_summary`'s completion percentage for a value creeping toward 100% after
  calibration locks, which is this mechanism's own early-warning signal; raising
  `CALIBRATION_MARGIN_RATIO` once several runs confirm the margin is genuinely too tight,
  never from a single run's data. A chunk that does overflow `num_predict` after
  calibration fails exactly the way an uncalibrated one always could —
  `ModelOutputError`, one file marked in error — not silently.
- **A manifest re-run after a code upgrade that changes the calibration constants**
  keeps whatever ratio its run already locked (persisted, never recomputed) — only a
  *new* run picks up new constant values. Consistent with how `num_ctx`/`num_predict`
  themselves already only take effect on a fresh manifest hash (ADR-0021).

## Related

- `glyphwell/tokens.py` (`chunk_token_budget`, `calibrate_response_ratio`, and the four
  named constants — each documents its own retuning trigger),
  `glyphwell/search/calibration.py` (`Calibration`), `glyphwell/search/engine.py`
  (`_load_calibration`, `_record_calibration_sample`), `glyphwell/db/schema_run.sql` and
  `glyphwell/db/migrations.py` (`runs.calibrated_response_ratio`, run schema version 2).
- ADR-0021 (token-budget chunking — amended by this ADR: the two-constraint shape and
  the context ceiling are unchanged, only the response-safety cap's ratio is no longer a
  blind constant), CLAUDE.md §7 (resume invariants, in particular deterministic chunk
  ordering).
