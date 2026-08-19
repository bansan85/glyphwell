"""Alias de types partagés (PEP 695).

Ces alias sont paresseux et sans coût d'exécution. Ils servent à rendre les signatures
lisibles et à distinguer des identifiants qui sont tous des chaînes mais ne sont pas
interchangeables : un identifiant IMDb, un nom de fichier OPUS et un identifiant de
phrase n'ont ni le même domaine ni la même provenance.
"""

from pydantic import JsonValue

__all__ = [
    "ImdbId",
    "JsonObject",
    "JsonValue",
    "LanguageCode",
    "OpusFileId",
    "OpusVersion",
    "SentenceId",
    "Sha256",
]

type ImdbId = str
"""Identifiant IMDb canonique, préfixe inclus : ``tt0133093``.

Le corpus OPUS porte la forme nue et zéro-paddée (``133093``) dans ses chemins ; la
normalisation vers cette forme canonique est centralisée dans `glyphwell.corpus.layout`.
"""

type OpusFileId = str
"""Nom du fichier de sous-titre dans le corpus OPUS, sans extension."""

type SentenceId = str
"""Attribut ``id`` d'une balise ``<s>`` du XML OPUS.

Ordinal **opaque** : ordonné, mais pas nécessairement contigu ni purement numérique. La
position dans le flux (`Sentence.index`) est ce qui fait autorité pour la reprise ; cet
identifiant n'est conservé que pour la traçabilité.
"""

type LanguageCode = str
"""Code de langue tel qu'utilisé par OPUS : ``en``, ``fr``, ..."""

type OpusVersion = str
"""Version d'une release OPUS : ``v2018``."""

type Sha256 = str
"""Empreinte SHA-256 en hexadécimal minuscule."""

type JsonObject = dict[str, JsonValue]
"""Objet JSON quelconque.

Utilisé aux frontières non typées (YAML, réponse du modèle) à la place de ``Any``, que
mypy interdit dans ce projet.
"""
