"""Stub minimal pour `opustools`, qui n'expose pas de typage.

`disallow_any_unimported` interdit `ignore_missing_imports` : sans ce stub, tout ce qui
traverse `opustools` deviendrait `Any`. N'y déclarer que la surface réellement utilisée par
`glyphwell.corpus.opus` — un stub trop large affirmerait des types non vérifiés.

Références : https://pypi.org/project/opustools/
"""

from collections.abc import Sequence

__all__ = ["OpusGet", "OpusRead"]

class OpusGet:
    """Télécharge des fichiers de corpus depuis l'index OPUS."""

    def __init__(
        self,
        directory: str | None = ...,
        source: str | None = ...,
        target: str | None = ...,
        release: str = ...,
        preprocess: str = ...,
        download_dir: str = ...,
        list_resources: bool = ...,
        suppress_prompts: bool = ...,
        database: str | None = ...,
    ) -> None: ...
    def get_files(self) -> None: ...
    def get_corpora_data(self, corpus: str) -> tuple[Sequence[object], int]: ...

class OpusRead:
    """Lit des alignements de phrases dans une archive OPUS."""

    def __init__(
        self,
        directory: str | None = ...,
        source: str | None = ...,
        target: str | None = ...,
        release: str = ...,
        preprocess: str = ...,
        download_dir: str = ...,
    ) -> None: ...
    def printPairs(self) -> None: ...  # noqa: N802
