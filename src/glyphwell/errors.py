"""Hiérarchie d'exceptions du projet.

Toute erreur attendue dérive de `GlyphwellError` : la CLI peut ainsi présenter un message
lisible plutôt qu'une trace, et laisser remonter les vraies anomalies de programmation.
"""

__all__ = [
    "ConfigurationError",
    "CorpusError",
    "CorpusLayoutError",
    "CorpusReadError",
    "DatabaseError",
    "GlyphwellError",
    "ManifestError",
    "MetadataError",
    "ModelOutputError",
    "OllamaError",
    "SchemaVersionError",
    "SearchError",
]


class GlyphwellError(Exception):
    """Racine de toutes les erreurs attendues de glyphwell."""


class ConfigurationError(GlyphwellError):
    """Configuration invalide ou incomplète (variables d'environnement, chemins)."""


class DatabaseError(GlyphwellError):
    """Échec d'une opération SQLite."""


class SchemaVersionError(DatabaseError):
    """La base ouverte ne porte pas la version de schéma attendue."""


class CorpusError(GlyphwellError):
    """Problème sur le corpus de sous-titres."""


class CorpusLayoutError(CorpusError):
    """Un chemin ne respecte pas l'arborescence attendue du corpus OPUS."""


class CorpusReadError(CorpusError):
    """Un fichier de sous-titre est illisible ou irrécupérablement mal formé."""


class MetadataError(GlyphwellError):
    """Échec du téléchargement, de l'import ou de la résolution des métadonnées."""


class ManifestError(GlyphwellError):
    """Manifeste de recherche introuvable, mal formé ou invalide."""


class OllamaError(GlyphwellError):
    """Échec de communication avec le serveur Ollama."""


class ModelOutputError(OllamaError):
    """La réponse du modèle ne respecte pas le schéma de sortie du manifeste."""


class SearchError(GlyphwellError):
    """Échec de la planification ou de l'exécution d'une recherche."""
