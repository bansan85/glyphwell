"""Token-count estimation, used to size chunks against a model's context window.

No tokenizer dependency is available: Ollama serves many different model families, each
with its own tokenizer, and none is known ahead of a call. `estimate_tokens` is therefore
a conservative character-based heuristic, not an exact count — deliberately biased toward
*overestimating* token usage, since Ollama silently truncates a context that overflows
`options.num_ctx` rather than raising an error.

`chunk_token_budget` bounds a chunk by two independent constraints, not `num_ctx` alone:
see its docstring. Feeding in as much as physically fits in `num_ctx` sounds efficient,
but for a prompt whose response scales with its input (an array of findings, one per
interesting line) it just moves the truncation from the request to the response: Ollama
stops generating at `num_predict`, mid-JSON, once the model has more to describe than the
response budget allows.

`response_ratio` (`calibrate_response_ratio`, consumed by `glyphwell.search.calibration`)
replaces ADR-0021's blind `1x num_predict` response-safety assumption with one measured
from a run's own early completions — see ADR-0022.
"""

import math
from typing import TYPE_CHECKING, Final

from glyphwell.errors import ManifestError

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "CALIBRATION_MARGIN_RATIO",
    "CALIBRATION_MIN_CHUNK_TOKENS",
    "CALIBRATION_SAMPLE_SIZE",
    "CHARS_PER_TOKEN",
    "DEFAULT_RESPONSE_RATIO",
    "SAFETY_MARGIN_RATIO",
    "calibrate_response_ratio",
    "chunk_token_budget",
    "estimate_tokens",
]

CHARS_PER_TOKEN: Final = 3.2
"""Conservative average characters per token for English dialogue text."""

SAFETY_MARGIN_RATIO: Final = 0.15
"""Fraction of `num_ctx` reserved as headroom.

Absorbs what the character-based estimate cannot see: chat-template special tokens, the
context cost of the JSON-schema `format` payload, and the estimator's own error. Expressed
as a ratio of `num_ctx` rather than a flat token count, so it scales with the context
window instead of being too tight at a small `num_ctx` or wastefully large at a big one.
"""

DEFAULT_RESPONSE_RATIO: Final = 1.0
"""Response-to-input token ratio assumed before a run's calibration has locked in (see
`CALIBRATION_SAMPLE_SIZE`), and forever on a run whose calibration never locks. Keeps
`chunk_token_budget`'s original `min(ceiling, num_predict)` behavior (ADR-0021) as the
safe starting point while no per-manifest data exists yet. Do not tune this value: it is
a fallback, not a target — retune `CALIBRATION_MARGIN_RATIO` instead once real data
exists (ADR-0022)."""

CALIBRATION_MIN_CHUNK_TOKENS: Final = 200
"""Minimum estimated size (`estimate_tokens(chunk.render())`) a chunk must have for its
completion to count as a calibration sample.

Why: a near-empty chunk (e.g. a file's last few sentences) that happens to trigger a
match produces a wildly inflated ratio — a 150-token completion over a 30-token chunk is
a "5.0" ratio that says nothing about how a full-sized chunk behaves — and one such
sample would dominate the max-based statistic in `calibrate_response_ratio`, defeating
calibration. Raise this if a run's locked ratio still looks implausibly high; check the
chunk sizes in the debug log's `_token_summary` lines feeding that run's calibration."""

CALIBRATION_SAMPLE_SIZE: Final = 50
"""Number of qualifying completions (`chunk_tokens >= CALIBRATION_MIN_CHUNK_TOKENS`)
observed before the response ratio locks in for the rest of the run.

Retuning: raise this if a run's calibrated ratio turns out to have been set from an
unrepresentative early stretch of the corpus — the deterministic queue order
(`ORDER BY rel_path`) means the same stretch repeats across runs of the same manifest, so
a bad draw is not self-correcting. Lower it if the conservative pre-calibration stretch
(running at `DEFAULT_RESPONSE_RATIO`) is itself costing meaningful time on small corpora.
There is no principled default yet — 50 is a first cut sized to smooth out per-chunk
noise without stalling small runs; revisit once a few real runs' calibration logs exist
(look for the "calibrated response ratio locked" message)."""

CALIBRATION_MARGIN_RATIO: Final = 0.5
"""Safety margin applied on top of the worst observed ratio:
`locked_ratio = max_observed_ratio * (1 + CALIBRATION_MARGIN_RATIO)`.

Guards against the calibration sample not containing the densest chunk the rest of the
run will produce — the residual risk this whole mechanism carries, since a calibrated
run can no longer fall back on `DEFAULT_RESPONSE_RATIO`'s "safe by construction" 1x cap.

Retuning: raise this if a run's debug log ever shows a post-calibration completion
landing close to `num_predict` (`_token_summary`'s completion percentage creeping toward
100%) — that is the mechanism's own early-warning signal that the locked ratio is too
tight for content the calibration sample under-represented. Lower it only once several
full runs confirm the margin is consistently far wider than needed (calibrated
completions staying well under `num_predict`) — never lower it from a single run's data."""


def estimate_tokens(text: str) -> int:
    """Conservative token-count estimate for `text`."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def calibrate_response_ratio(samples: "Sequence[tuple[int, int]]") -> float | None:
    """Derives a locked response ratio from `(chunk_tokens, completion_tokens)` pairs.

    Each pair is one real completion: `chunk_tokens` is `estimate_tokens(chunk.render())`
    for the chunk actually sent, `completion_tokens` Ollama's own `eval_count` for the
    response it produced — both already expressed in the same units `chunk_token_budget`
    consumes, so no conversion to a model's real tokenizer is ever needed (none is
    available anyway, see the module docstring). Only pairs with
    `chunk_tokens >= CALIBRATION_MIN_CHUNK_TOKENS` qualify.

    Returns `None` before `CALIBRATION_SAMPLE_SIZE` qualifying pairs have been given, or
    if every qualifying pair had a zero-token completion (nothing to calibrate a ratio
    from) — the caller (`glyphwell.search.calibration.Calibration`) keeps accumulating
    and stays on `DEFAULT_RESPONSE_RATIO` meanwhile.
    """
    qualifying = [pair for pair in samples if pair[0] >= CALIBRATION_MIN_CHUNK_TOKENS]
    if len(qualifying) < CALIBRATION_SAMPLE_SIZE:
        return None
    max_ratio = max(completion / chunk for chunk, completion in qualifying)
    if max_ratio <= 0:
        return None
    return max_ratio * (1 + CALIBRATION_MARGIN_RATIO)


def chunk_token_budget(
    *,
    num_ctx: int,
    num_predict: int,
    overhead_text: str,
    response_ratio: float = DEFAULT_RESPONSE_RATIO,
) -> int:
    """Tokens available for a chunk's sentences.

    Bounded by two independent constraints:

    - The **context ceiling**: what is left of `num_ctx` once `num_predict`, the rendered
      prompt overhead (`overhead_text` — `prompt.system` and `prompt.user` rendered with
      an empty chunk), and the safety margin are subtracted. Guarantees the prompt itself
      fits.
    - **The response-safety cap**, `num_predict / response_ratio`: a chunk far larger than
      the response budget all but guarantees a truncated, invalid response for any task
      whose output scales with its input (one JSON finding described per interesting
      line, say) — Ollama stops generating exactly at `num_predict`, mid-JSON, with no
      graceful degradation. At the default `response_ratio` (`DEFAULT_RESPONSE_RATIO`,
      1.0) this cap is just `num_predict` itself — ADR-0021's original, evidence-free
      assumption. `glyphwell.search.calibration.Calibration` supplies a smaller,
      empirically measured `response_ratio` once a run has observed enough of its own
      completions (ADR-0022), which raises this cap and therefore densifies chunks for a
      task whose response does not scale much with its input. A manifest can also widen
      it by hand, by raising `num_predict` beyond what a single response actually needs.

    Raises:
        ManifestError: the context ceiling alone is `< 1` — `num_ctx` cannot cover
            `num_predict`, the prompt overhead, and the safety margin combined, so the
            manifest is misconfigured regardless of any chunk content.
    """
    margin = math.ceil(SAFETY_MARGIN_RATIO * num_ctx)
    ceiling = num_ctx - num_predict - estimate_tokens(overhead_text) - margin
    if ceiling < 1:
        message = (
            f"options.num_ctx ({num_ctx}) leaves no room for a chunk once num_predict "
            f"({num_predict}), the prompt overhead, and the {SAFETY_MARGIN_RATIO:.0%} "
            "safety margin are subtracted: raise num_ctx or shorten the prompt"
        )
        raise ManifestError(message)
    predict_cap = math.floor(num_predict / response_ratio)
    return min(ceiling, predict_cap)
