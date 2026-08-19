"""Alias de types partagés (PEP 695).

Ces alias sont paresseux et sans coût d'exécution. Ils servent à rendre les signatures
lisibles et à distinguer des identifiants qui sont tous des chaînes mais ne sont pas
interchangeables : un identifiant IMDb, un identifiant de sous-titre opensubtitles.org
et un identifiant de phrase n'ont ni le même domaine ni la même provenance.
"""

from pydantic import JsonValue

__all__ = [
    "ImdbId",
    "JsonObject",
    "JsonValue",
    "LanguageCode",
    "OpenSubtitlesFileId",
    "OpusVersion",
    "SentenceId",
    "Sha256",
]

type ImdbId = str
"""Identifiant IMDb canonique, préfixe inclus : ``tt0133093``.

L'archive OPUS porte la forme nue (``133093``, ``1596342``) dans ses chemins ; la
normalisation vers cette forme canonique est centralisée dans `glyphwell.corpus.layout`.
"""

type OpenSubtitlesFileId = str
"""Identifiant du sous-titre sur opensubtitles.org : ``1957893755``.

C'est lui que porte le nom de fichier dans l'archive OPUS. Il désigne une *traduction*
précise, là où `ImdbId` désigne l'œuvre : un même film a un `ImdbId` et autant
d'identifiants de sous-titres que de versions publiées. Permet de remonter à
``https://www.opensubtitles.org/en/subtitles/<id>``.
"""

type SentenceId = str
"""Attribut ``id`` d'une balise ``<s>`` du XML OPUS.

Ordinal **opaque** : ordonné, mais pas nécessairement contigu ni purement numérique. La
position dans le flux (`Sentence.index`) est ce qui fait autorité pour la reprise ; cet
identifiant n'est conservé que pour la traçabilité.
"""

type LanguageCode = str
"""Code de langue tel qu'utilisé par OPUS : ``en``, ``fr``, ..."""

type OpusVersion = str
"""Version d'une release OPUS : ``v2024``."""

type Sha256 = str
"""Empreinte SHA-256 en hexadécimal minuscule."""

type JsonObject = dict[str, JsonValue]
"""Objet JSON quelconque.

Utilisé aux frontières non typées (YAML, réponse du modèle) à la place de ``Any``, que
mypy interdit dans ce projet.
"""
