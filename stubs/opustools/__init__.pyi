"""Stub minimal pour `opustools`, qui n'expose pas de typage.

`disallow_any_unimported` interdit `ignore_missing_imports` : sans ce stub, tout ce qui
traverse `opustools` deviendrait `Any`. N'y déclarer que la surface réellement utilisée par
`glyphwell.corpus.opus` — un stub trop large affirmerait des types non vérifiés.

Vérifié contre opustools 1.8.3 (`opustools/opus_get.py`). Le stub précédent affirmait un
ordre de paramètres et un type de retour faux ; ne pas le réécrire de mémoire.

`get_files()` et `get_corpora_data()` sont délibérément absents : le téléchargement passe
par `httpx` (cf. le docstring de `glyphwell.corpus.opus`). D'`OpusGet` on ne retient que ce
qui décrit le contrat de l'API OPUS — l'URL de l'index et le nommage des archives.

Références : https://pypi.org/project/opustools/
"""

from collections.abc import Mapping

__all__ = ["OpusGet"]

class OpusGet:
    """Interroge l'index OPUS et télécharge les archives.

    `directory` est le nom du corpus, `source` la langue — pas l'inverse. `url` porte les
    paramètres de la requête et se termine par ``&``, à retirer avant appel.
    `make_file_name` lit les clés ``url`` et ``version`` de l'enregistrement.
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
