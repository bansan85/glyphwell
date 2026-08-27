"""Empirical calibration of the chunk token budget's response-safety cap.

ADR-0021 originally capped a chunk's input size at `1x num_predict` tokens — a ratio
picked with no data to justify it over any other value: safe by construction, but
possibly far too conservative for a manifest whose response does not scale much with its
input. `Calibration` replaces that blind constant with one measured from a run's own
early completions, once enough of them have been observed — see ADR-0022 and
`glyphwell.tokens.calibrate_response_ratio`.

Confined to the engine's single DB-owning thread, exactly like `search.checkpoint`:
`Calibration` is plain mutable state, never touched by a worker thread (workers only
ever call `LlmClient.complete`, pure I/O — see `search/engine.py`'s module docstring).
"""

from dataclasses import dataclass, field

from glyphwell.tokens import DEFAULT_RESPONSE_RATIO, calibrate_response_ratio

__all__ = ["Calibration"]


@dataclass(slots=True)
class Calibration:
    """A run's calibration state: accumulated samples, and the ratio once locked.

    `locked_ratio` is seeded from `runs.calibrated_response_ratio` at the start of a run
    or resume (see `search/engine.py::_load_calibration`) and, once set — in memory or in
    the database — never changes again for the run's lifetime. That is what keeps chunk
    sizing deterministic per manifest (CLAUDE.md §7): a value that could keep drifting
    would make `Chunk.index` stop designating a stable sentence range across a resume.
    """

    locked_ratio: float | None = None
    _samples: list[tuple[int, int]] = field(default_factory=list)

    @property
    def response_ratio(self) -> float:
        """The ratio to size the next chunk with: the locked value, or the safe default."""
        return self.locked_ratio if self.locked_ratio is not None else DEFAULT_RESPONSE_RATIO

    def record(self, *, chunk_tokens: int, completion_tokens: int) -> float | None:
        """Adds one observed `(chunk_tokens, completion_tokens)` sample.

        Returns the newly locked ratio the first time enough samples qualify (see
        `glyphwell.tokens.calibrate_response_ratio`); `None` on every call before or
        after that point — the caller persists the ratio only on that one transition.
        """
        if self.locked_ratio is not None:
            return None
        self._samples.append((chunk_tokens, completion_tokens))
        ratio = calibrate_response_ratio(self._samples)
        if ratio is None:
            return None
        self.locked_ratio = ratio
        return ratio
