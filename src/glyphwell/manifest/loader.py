"""Chargement et hachage d'un manifeste de recherche.

Le hash du texte source identifie la recherche : modifier le YAML produit un hash différent,
donc un nouveau run, au lieu de mélanger des résultats obtenus avec deux prompts distincts.
C'est aussi ce qui permet de reprendre en toute sécurité — on vérifie que le manifeste n'a
pas bougé depuis le lancement.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from glyphwell.errors import ManifestError
from glyphwell.manifest.model import SearchManifest
from glyphwell.types import Sha256

__all__ = ["LoadedManifest", "load", "manifest_hash"]


@dataclass(frozen=True, slots=True, kw_only=True)
class LoadedManifest:
    """Un manifeste validé, accompagné de son origine et de son empreinte.

    Attributes:
        manifest: le manifeste validé.
        path: fichier d'où il provient.
        source: texte YAML intégral, archivé dans `runs.manifest_snapshot` pour qu'un run
            reste interprétable même si le fichier change ensuite.
        hash: empreinte du texte source.
    """

    manifest: SearchManifest
    path: Path
    source: str
    hash: Sha256

    @property
    def name(self) -> str:
        """Nom de la recherche, tel que déclaré dans le manifeste."""
        return self.manifest.name

    @property
    def model(self) -> str:
        """Modèle Ollama demandé."""
        return self.manifest.model


def manifest_hash(source: str) -> Sha256:
    """Calcule l'empreinte d'un manifeste à partir de son texte source.

    Les fins de ligne sont normalisées avant hachage : un même manifeste doit produire la
    même empreinte selon qu'il a été récupéré sous Windows ou sous Linux. Rien d'autre n'est
    normalisé — un commentaire modifié change bien l'empreinte, et c'est voulu : on préfère
    créer un run distinct plutôt que de risquer de réutiliser des résultats issus d'une
    version différente du fichier.
    """
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load(path: str | Path) -> LoadedManifest:
    """Lit, valide et hache un manifeste de recherche.

    Args:
        path: chemin du fichier YAML.

    Returns:
        Le manifeste validé, son texte source et son empreinte.

    Raises:
        ManifestError: fichier absent, YAML mal formé, ou manifeste invalide.
    """
    manifest_path = Path(path)

    try:
        source = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        message = f"manifeste illisible : {manifest_path} ({exc})"
        raise ManifestError(message) from exc

    try:
        # `safe_load` n'instancie aucun objet Python : un manifeste reste de la donnée.
        # Le résultat est délibérément traité comme `object`, puis resserré par pydantic.
        raw: object = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        message = f"YAML mal formé dans {manifest_path} : {exc}"
        raise ManifestError(message) from exc

    if not isinstance(raw, dict):
        kind = type(raw).__name__
        message = f"{manifest_path} doit contenir un objet YAML à la racine, trouvé : {kind}"
        raise ManifestError(message)

    try:
        manifest = SearchManifest.model_validate(raw)
    except ValidationError as exc:
        message = f"manifeste invalide ({manifest_path}) :\n{exc}"
        raise ManifestError(message) from exc

    return LoadedManifest(
        manifest=manifest,
        path=manifest_path,
        source=source,
        hash=manifest_hash(source),
    )
