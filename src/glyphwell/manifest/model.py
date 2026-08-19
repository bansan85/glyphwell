"""Modèle du manifeste de recherche.

Un manifeste est un YAML déclaratif : prompt, modèle Ollama, filtres de sélection,
paramètres de fenêtrage, pré-filtre textuel et schéma de sortie attendu. Il est validé par
pydantic à l'ouverture, ce qui fait échouer une recherche mal décrite avant le premier appel
au modèle plutôt qu'au millième fichier.

Aucun code n'est exécuté depuis un manifeste : c'est de la donnée, versionnable, diffable et
hachable.
"""

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

__all__ = [
    "ChunkConfig",
    "OutputConfig",
    "OutputFormat",
    "PrefilterConfig",
    "PrefilterMode",
    "PromptConfig",
    "SearchManifest",
    "SelectConfig",
    "YearRange",
]

type OutputFormat = Literal["json", "text"]


class _Base(BaseModel):
    """Base commune : un champ inconnu est une erreur, pas un silence.

    Une faute de frappe dans une clé du YAML ne doit pas se traduire par un filtre
    silencieusement ignoré.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class PrefilterMode(StrEnum):
    """Mode de pré-filtrage appliqué avant tout appel au modèle."""

    ANY = "any"
    """Retenir la fenêtre si au moins un motif est présent."""

    ALL = "all"
    """Retenir la fenêtre si tous les motifs sont présents."""

    NONE = "none"
    """Retenir la fenêtre si aucun motif n'est présent."""

    OFF = "off"
    """Pas de pré-filtrage : toutes les fenêtres partent au modèle."""


class ChunkConfig(_Base):
    """Fenêtrage : unité d'appel au modèle et unité de reprise."""

    size: int = Field(default=80, ge=1, description="Nombre de phrases par fenêtre.")
    overlap: int = Field(
        default=10,
        ge=0,
        description=(
            "Phrases répétées d'une fenêtre à la suivante, pour ne pas couper un passage en deux."
        ),
    )

    @model_validator(mode="after")
    def _check_overlap(self) -> Self:
        """Un recouvrement supérieur ou égal à la taille empêcherait la fenêtre d'avancer."""
        if self.overlap >= self.size:
            message = f"chunk.overlap ({self.overlap}) doit être < chunk.size ({self.size})"
            raise ValueError(message)
        return self


class PrefilterConfig(_Base):
    """Pré-filtre textuel, évalué localement.

    Un appel LLM coûte des ordres de grandeur de plus qu'une recherche de sous-chaîne : sur
    des centaines de milliers de sous-titres, un pré-filtre bien choisi change la durée
    totale d'une recherche.
    """

    mode: PrefilterMode = PrefilterMode.OFF
    patterns: tuple[str, ...] = ()
    case_sensitive: bool = False
    regex: bool = Field(
        default=False,
        description="Interpréter les motifs comme des expressions régulières.",
    )

    @model_validator(mode="after")
    def _check_patterns(self) -> Self:
        """Un mode actif sans motif ne filtrerait rien, ou tout : c'est une erreur de saisie."""
        if self.mode is not PrefilterMode.OFF and not self.patterns:
            message = f"prefilter.mode = {self.mode.value} exige au moins un motif"
            raise ValueError(message)
        return self


class YearRange(_Base):
    """Intervalle d'années, bornes incluses. `None` signifie « pas de borne »."""

    min: int | None = None
    max: int | None = None

    @model_validator(mode="after")
    def _check_order(self) -> Self:
        """Bornes inversées : plus probablement une erreur qu'une intention."""
        if self.min is not None and self.max is not None and self.min > self.max:
            message = f"select.years.min ({self.min}) > select.years.max ({self.max})"
            raise ValueError(message)
        return self


class SelectConfig(_Base):
    """Sélection des sous-titres à analyser.

    Les filtres portant sur le titre (type, année, contenu adulte) exigent que les datasets
    IMDb aient été importés ; sans eux, les fichiers non résolus sont écartés.
    """

    languages: tuple[str, ...] = ("en",)
    title_types: tuple[str, ...] = Field(
        default=(),
        description="Types IMDb retenus (movie, tvEpisode, tvSeries...). Vide = tous.",
    )
    years: YearRange = YearRange()
    exclude_adult: bool = True
    imdb_ids: tuple[str, ...] | None = Field(
        default=None,
        description="Restreint la recherche à ces titres. `null` = tout le corpus.",
    )


class PromptConfig(_Base):
    """Gabarits de prompt.

    Substitutions disponibles : ``{{ title }}``, ``{{ year }}``, ``{{ imdb_id }}``,
    ``{{ first_id }}``, ``{{ last_id }}``, ``{{ chunk }}``.
    """

    system: str | None = None
    user: str = Field(min_length=1)


class OutputConfig(_Base):
    """Forme attendue de la réponse du modèle."""

    format: OutputFormat = "json"
    json_schema: dict[str, JsonValue] | None = Field(
        default=None,
        alias="schema",
        description=(
            "JSON Schema transmis à Ollama pour contraindre la génération, puis revérifié "
            "côté client."
        ),
    )

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _check_schema(self) -> Self:
        """Un schéma n'a de sens qu'en sortie JSON."""
        if self.format == "text" and self.json_schema is not None:
            message = "output.schema est inutilisable avec output.format = text"
            raise ValueError(message)
        return self


class SearchManifest(_Base):
    """Un manifeste de recherche complet."""

    name: str = Field(min_length=1, description="Identifiant lisible de la recherche.")
    description: str | None = None
    model: str = Field(min_length=1, description="Modèle Ollama, par exemple llama3.1:8b.")
    options: dict[str, JsonValue] = Field(
        default_factory=dict,
        description="Options passées telles quelles à Ollama (temperature, num_ctx...).",
    )

    select: SelectConfig = SelectConfig()
    chunk: ChunkConfig = ChunkConfig()
    prefilter: PrefilterConfig = PrefilterConfig()
    prompt: PromptConfig
    output: OutputConfig = OutputConfig()

    match_when: str | None = Field(
        default=None,
        description=(
            "Nom du champ booléen de la réponse qui détermine `results.matched`. "
            "`null` : tout résultat produit est considéré comme une correspondance."
        ),
    )
