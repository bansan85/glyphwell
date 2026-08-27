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
"""

import math
from typing import Final

from glyphwell.errors import ManifestError

__all__ = ["CHARS_PER_TOKEN", "SAFETY_MARGIN_RATIO", "chunk_token_budget", "estimate_tokens"]

CHARS_PER_TOKEN: Final = 3.2
"""Conservative average characters per token for English dialogue text."""

SAFETY_MARGIN_RATIO: Final = 0.15
"""Fraction of `num_ctx` reserved as headroom.

Absorbs what the character-based estimate cannot see: chat-template special tokens, the
context cost of the JSON-schema `format` payload, and the estimator's own error. Expressed
as a ratio of `num_ctx` rather than a flat token count, so it scales with the context
window instead of being too tight at a small `num_ctx` or wastefully large at a big one.
"""


def estimate_tokens(text: str) -> int:
    """Conservative token-count estimate for `text`."""
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def chunk_token_budget(*, num_ctx: int, num_predict: int, overhead_text: str) -> int:
    """Tokens available for a chunk's sentences.

    Bounded by two independent constraints:

    - The **context ceiling**: what is left of `num_ctx` once `num_predict`, the rendered
      prompt overhead (`overhead_text` — `prompt.system` and `prompt.user` rendered with
      an empty chunk), and the safety margin are subtracted. Guarantees the prompt itself
      fits.
    - **`num_predict` itself**: a chunk far larger than the response budget all but
      guarantees a truncated, invalid response for any task whose output scales with its
      input (one JSON finding described per interesting line, say) — Ollama stops
      generating exactly at `num_predict`, mid-JSON, with no graceful degradation.
      Capping the chunk to `num_predict` keeps the two in the same rough proportion a
      hand-picked `chunk.size` used to be tuned to alongside `num_predict`, before chunk
      sizing became automatic. A manifest whose response schema is small and does not
      scale with input (a lone boolean, say) can still get denser chunks by raising
      `num_predict` beyond what a single response actually needs.

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
    return min(ceiling, num_predict)
