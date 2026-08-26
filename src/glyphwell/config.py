"""Project configuration.

All values can be overridden via an environment variable prefixed with
``GLYPHWELL_`` or via a ``.env`` file at the root (see ``.env.example``).
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["LogLevel", "Settings", "resolve_run_database_path"]

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
    catalog_database: Path | None = Field(
        default=None,
        description=(
            "Path to the catalog SQLite database (titles, subtitle_files, "
            "corpus_downloads, imports). Defaults to <data_dir>/glyphwell.db."
        ),
    )
    run_database: Path | None = Field(
        default=None,
        description=(
            "Path to a search's run-state database (runs, run_files, results). Only "
            "meaningful together with a manifest; see resolve_run_database_path(). "
            "Defaults to <data_dir>/<manifest filename without .yaml>.db."
        ),
    )

    ollama_host: str = Field(default="http://localhost:11434")
    ollama_timeout: float = Field(default=300.0, gt=0)

    concurrency: int = Field(
        default=1,
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

    verify_tls: bool = Field(
        default=True,
        description=(
            "Verify the TLS certificate of the servers downloaded from (OPUS, IMDb). "
            "`false` is the equivalent of wget's --no-check-certificate, also reachable "
            "as the global CLI option of that name. See `glyphwell.http`."
        ),
    )

    log_level: LogLevel = Field(default="INFO")

    @property
    def catalog_database_path(self) -> Path:
        """Effective path to the catalog SQLite database."""
        return (
            self.catalog_database
            if self.catalog_database is not None
            else self.data_dir / "glyphwell.db"
        )

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


def resolve_run_database_path(settings: Settings, *, manifest_path: Path) -> Path:
    """Effective path to a search's run database.

    Defaults to ``<data_dir>/<manifest filename stem>.db`` — the manifest's own file
    stem, not its declared `name`: two manifests may share a `name`, but never a
    filename in the same directory, so the default can't collide by surprise.
    """
    return settings.run_database or settings.data_dir / f"{manifest_path.stem}.db"
