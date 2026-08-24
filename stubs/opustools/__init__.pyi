"""Minimal stub for `opustools`, which ships no typing.

`disallow_any_unimported` forbids `ignore_missing_imports`: without this stub, everything
that crosses `opustools` would become `Any`. Declare here only the surface actually used by
`glyphwell.corpus.opus` — a stub any broader would assert types that were never checked.

Verified against opustools 1.8.3 (`opustools/opus_get.py`). The previous stub asserted a
wrong parameter order and a wrong return type; do not rewrite it from memory.

`get_files()` and `get_corpora_data()` are deliberately absent: downloading goes through
`httpx` instead (see the docstring of `glyphwell.corpus.opus`). Of `OpusGet` we only keep
what describes the OPUS API contract — the index URL and archive naming.

References: https://pypi.org/project/opustools/
"""

from collections.abc import Mapping

__all__ = ["OpusGet"]

class OpusGet:
    """Queries the OPUS index and downloads archives.

    `directory` is the corpus name, `source` the language — not the other way around. `url`
    carries the request parameters and ends with ``&``, to be stripped before calling.
    `make_file_name` reads the ``url`` and ``version`` keys of the record.
    """

    url: str

    def __init__(
        self,
        source: str | None = ...,
        target: str | None = ...,
        directory: str | None = ...,
        release: str = ...,
        preprocess: str = ...,
        list_resources: bool = ...,
        list_languages: bool = ...,
        list_corpora: bool = ...,
        download_dir: str = ...,
        local_db: bool = ...,
        suppress_prompts: bool = ...,
        database: str = ...,
    ) -> None: ...
    def make_file_name(self, c: Mapping[str, str]) -> str: ...
