"""The project's exception hierarchy.

Every expected error derives from `GlyphwellError`: this lets the CLI present a readable
message instead of a traceback, while letting genuine programming errors propagate.
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
    """Root of all expected glyphwell errors."""


class ConfigurationError(GlyphwellError):
    """Invalid or incomplete configuration (environment variables, paths)."""


class DatabaseError(GlyphwellError):
    """Failure of a SQLite operation."""


class SchemaVersionError(DatabaseError):
    """The opened database does not carry the expected schema version."""


class CorpusError(GlyphwellError):
    """Problem with the subtitle corpus."""


class CorpusLayoutError(CorpusError):
    """A path does not conform to the expected OPUS corpus layout."""


class CorpusReadError(CorpusError):
    """A subtitle file is unreadable or irrecoverably malformed."""


class MetadataError(GlyphwellError):
    """Failure of metadata download, import, or resolution."""


class ManifestError(GlyphwellError):
    """Search manifest not found, malformed, or invalid."""


class OllamaError(GlyphwellError):
    """Failure to communicate with the Ollama server."""


class ModelOutputError(OllamaError):
    """The model's response does not conform to the manifest's output schema."""


class SearchError(GlyphwellError):
    """Failure of search planning or execution."""
