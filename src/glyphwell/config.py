"""Configuration du projet.

Toutes les valeurs sont surchargeables par variable d'environnement préfixée
``GLYPHWELL_`` ou par un fichier ``.env`` à la racine (voir ``.env.example``).
"""

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["LogLevel", "Settings"]

# Alias implicite, et non `type LogLevel = ...` (PEP 695) : Typer introspecte l'annotation à
# l'exécution et ne sait pas déballer un `TypeAliasType`, ce qui ferait échouer la
# construction de l'option `--log-level`. Ailleurs dans le projet, les alias PEP 695 sont la
# règle (cf. glyphwell.types).
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class Settings(BaseSettings):
    """Paramètres d'exécution résolus une fois au démarrage de la CLI."""

    model_config = SettingsConfigDict(
        env_prefix="GLYPHWELL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(
        default=Path("data"),
        description=(
            "Racine de toutes les données produites. Le corpus anglais complet pèse "
            "plusieurs dizaines de Go décompressés."
        ),
    )
    database: Path | None = Field(
        default=None,
        description="Chemin de la base SQLite. Par défaut : <data_dir>/glyphwell.db.",
    )

    ollama_host: str = Field(default="http://localhost:11434")
    ollama_timeout: float = Field(default=300.0, gt=0)

    concurrency: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Nombre de fenêtres analysées en parallèle par une recherche.",
    )

    opus_corpus: str = Field(default="OpenSubtitles")
    opus_version: str = Field(
        default="v2024",
        description="Release OPUS. La plus récente, donc la plus complète : 35,8 Go en `en`.",
    )
    opus_language: str = Field(default="en")

    log_level: LogLevel = Field(default="INFO")

    @property
    def database_path(self) -> Path:
        """Chemin effectif de la base SQLite."""
        return self.database if self.database is not None else self.data_dir / "glyphwell.db"

    @property
    def corpus_dir(self) -> Path:
        """Répertoire du corpus : c'est là que vit l'archive OPUS.

        L'archive n'est jamais décompressée (cf. `glyphwell.corpus.archive`) : ce
        répertoire contient un fichier zip par couple (release, langue), pas une
        arborescence de sous-titres.
        """
        return self.data_dir / "corpus"

    @property
    def downloads_dir(self) -> Path:
        """TSV des datasets IMDb. L'archive OPUS, elle, vit dans `corpus_dir`."""
        return self.data_dir / "downloads"

    @property
    def exports_dir(self) -> Path:
        """Résultats exportés par ``glyphwell search export``."""
        return self.data_dir / "exports"

    def ensure_directories(self) -> None:
        """Crée les répertoires de travail s'ils n'existent pas."""
        for directory in (self.data_dir, self.corpus_dir, self.downloads_dir, self.exports_dir):
            directory.mkdir(parents=True, exist_ok=True)
