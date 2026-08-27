# ADR-0023: Cite excerpts by a line range, not a flat id list

**Status**: Accepted
**Date**: 2026-08-27

## Context

`searches/example.yaml`'s schema asked the model to cite every sentence supporting a
finding individually, in an `excerpt_ids: array<integer>` field. `search/results.py`
reconstructed the sibling `excerpt` field by joining *exactly* those cited lines, in
order — nothing in between (ADR-0013's re-validation step is what performs this
reconstruction).

Real runs produced cases like:

```json
"excerpt_ids": [994, 996, 1021, 1036, 1043, 1044]
```

Six ids spread across a roughly 50-line span, glued into one `excerpt` string as if it
were one continuous quote. Nothing in the flat-list shape distinguishes "one continuous
passage the model cited sparsely" from "several unrelated mentions the model lumped
together" — the ambiguity is baked into the format itself, not just an occasional
mistake.

## Decision Drivers

- The reconstructed `excerpt` should read as an honest, contiguous quote — or the schema
  should force the model to say so isn't one, by splitting into several findings.
- The new field(s) must stay easy for constrained JSON generation to produce reliably:
  this project deliberately targets uncensored/abliterated community fine-tunes (ADR-0013)
  not benchmarked for strict schema compliance, so the shape itself should reduce
  opportunities to go wrong, not just document intent in a `description`.
- A sentence id is an opaque ordinal (`CLAUDE.md`, OPUS corpus notes): ordered, but not
  guaranteed contiguous or purely numeric. Any range semantics must be resolved by
  position in the chunk's own sentence sequence, never by arithmetic on the id values.
- No SQLite schema change: `results.payload` is an opaque JSON `TEXT` blob regardless of
  which field names a manifest's schema uses (ADR-0018's split of catalog/run databases
  didn't change this either).

## Considered Options

### Option 1: Keep the flat id list, ask the model to only cite a contiguous run

- **Pros**: no schema or reconstruction-code change.
- **Cons**: doesn't fix anything — the shape still lets the model cite a scattered set,
  and nothing catches it when it does. The problem is that the format has no way to
  *express* "this must be one contiguous range," only a convention asked for in prose.

### Option 2: A 2D array of `[min, max]` pairs, one array per finding

- **Pros**: keeps a single field; supports several ranges per finding directly, without
  relying on the model splitting into several `findings` entries.
- **Cons**: a nested array of pairs is a harder shape for constrained JSON generation to
  produce reliably than flat scalar fields — exactly the kind of structure ADR-0013's
  concern about non-benchmarked models warns against relying on. It also duplicates what
  `findings` (already an array) exists to do: represent several distinct pieces of
  evidence, each with its own category and description besides its excerpt.

### Option 3: Two scalar fields per finding, `excerpt_start_id`/`excerpt_end_id` (chosen)

- **Pros**: the simplest possible shape — two integers — for constrained generation to get
  right. One range per finding forces an explicit choice on the model: widen the range to
  cover a genuinely continuous passage, or emit a separate finding (with its own category
  and description, which disjoint evidence usually warrants anyway) for a separate one.
  No new array nesting; `findings` already provides the "several of these" mechanism.
- **Cons**: a finding whose evidence is two genuinely disjoint one-line mentions of the
  *same* technique, with nothing worth saying differently about them, now has to be
  reported as two findings instead of one with two short excerpts. Judged an acceptable
  trade: such a case is rare, and duplicating `concealment_category`/`method_description`
  across two findings costs little compared to the ambiguity the alternative left in.

## Decision

Replace `excerpt_ids` with two required integer fields, `excerpt_start_id` and
`excerpt_end_id` — the first and last line id of one continuous, inclusive range.
`search/results.py::_reconstruct_excerpts` now triggers reconstruction on that sibling
pair instead of a single `excerpt_ids` key, and `_join_line_range` resolves the range by
each id's *position* in the chunk's ordered `lines_by_id` (never by arithmetic on the id
values), joining every line from start to end inclusive — including lines the model never
explicitly cited. An inverted range (start positioned after end) is rejected with
`ModelOutputError`, the same way an out-of-chunk id already was.

The schema's field `description`s and the manifest's `prompt.system` (`searches/
example.yaml`) both spell out the same rule: cite one continuous range per finding; if the
evidence spans several disjoint passages, report each as its own finding with its own
narrower range, rather than widening one range to bridge the gap.

## Rationale

Two flat scalar fields are the shape most likely to survive a schema-unreliable model
intact, and they make the model's grouping decision — one continuous passage vs. several
distinct ones — visible in the output's own structure instead of buried in an id list a
reader has to eyeball for gaps. Reusing `findings` for "several excerpts" avoids inventing
a second array-of-ranges construct when one array (already required, already carrying
per-finding metadata) does the job.

## Consequences

### Positive

- A reconstructed `excerpt` is always a genuine contiguous quote from the chunk, never a
  collage of disconnected lines presented as one.
- The model's grouping choice (one finding vs. several) is now explicit in how many
  `findings` entries it emits, not implicit in how it happened to space out an id list.
- Two integers are a smaller, simpler generation target than a variable-length array.

### Negative

- Disjoint evidence for what is genuinely one finding now costs a duplicated
  `concealment_category`/`method_description` per extra finding.
- Every existing manifest using the old `excerpt_ids` convention (only
  `searches/example.yaml` in this repo) needs its schema and prompt updated together;
  there is no compatibility shim — `search/results.py` only recognizes the new field
  names.

### Risks

- A model could still emit a technically well-formed but semantically wrong range (e.g.
  needlessly wide, papering over what should have been split). The schema/prompt wording
  discourages it, but nothing enforces it beyond that — the same trust boundary ADR-0013
  already accepts for schema compliance in general.

## Related

- `search/results.py` (`_reconstruct_excerpts`, `_join_line_range`), `search/engine.py`
  (`_format_match`), `searches/example.yaml`.
- ADR-0013 (client-side re-validation, which this reconstruction is part of).
- `CLAUDE.md` §6 (sentence ids as opaque ordinals — the reason the range is
  position-resolved, not arithmetic).
