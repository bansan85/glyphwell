"""Project configuration.

All values can be overridden via an environment variable prefixed with
``GLYPHWELL_`` or via a ``.env`` file at the root (see ``.env.example``).
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["LogLevel", "Settings"]

# Implicit alias, not `type LogLevel = ...` (PEP 695): Typer introspects the annotation at
# runtime and can't unwrap a `TypeAliasType`, which would break the construction of the
# `--log-level` option. Elsewhere in the project, PEP 695 aliases are the rule (see
# glyphwell.types).
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Runtime settings resolved once at CLI startup."""

    model_config = SettingsConfigDict(
        env_prefix="GLYPHWELL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(
        default=Path("data"),
        description=(
            "Root of all produced data. The full English corpus weighs several dozen "
            "GB uncompressed."
        ),
    )
    database: Path | None = Field(
        default=None,
        description="Path to the SQLite database. Defaults to <data_dir>/glyphwell.db.",
    )

    ollama_host: str = Field(default="http://localhost:11434")
    ollama_timeout: float = Field(default=300.0, gt=0)

    concurrency: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Number of chunks analyzed in parallel by a search.",
    )

    opus_corpus: str = Field(default="OpenSubtitles")
    opus_version: str = Field(
        default="v2024",
        description="OPUS release. The most recent, hence the most complete: 35.8 GB in `en`.",
    )
    opus_language: str = Field(default="en")

    log_level: LogLevel = Field(default="INFO")

    @property
    def database_path(self) -> Path:
        """Effective path to the SQLite database."""
        return self.database if self.database is not None else self.data_dir / "glyphwell.db"

    @property
    def corpus_dir(self) -> Path:
        """Corpus directory: this is where the OPUS archive lives.

        The archive is never decompressed (see `glyphwell.corpus.archive`): this
        directory contains one zip file per (release, language) pair, not a
        subtitle layout.
        """
        return self.data_dir / "corpus"

    @property
    def downloads_dir(self) -> Path:
        """IMDb dataset TSVs. The OPUS archive, meanwhile, lives in `corpus_dir`."""
        return self.data_dir / "downloads"

    @property
    def exports_dir(self) -> Path:
        """Results exported by ``glyphwell search export``."""
        return self.data_dir / "exports"

    def ensure_directories(self) -> None:
        """Creates the working directories if they don't exist."""
        for directory in (self.data_dir, self.corpus_dir, self.downloads_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)
