"""Loading and hashing a search manifest.

The hash of the source text identifies the search: modifying the YAML produces a different
hash, hence a new run, instead of mixing results obtained with two distinct prompts. It is
also what makes resuming safe — we verify that the manifest has not changed since launch.
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
    """A validated manifest, together with its origin and its checksum.

    Attributes:
        manifest: the validated manifest.
        path: file it comes from.
        source: full YAML text, archived in `runs.manifest_snapshot` so a run stays
            interpretable even if the file changes afterward.
        hash: checksum of the source text.
    """

    manifest: SearchManifest
    path: Path
    source: str
    hash: Sha256

    @property
    def name(self) -> str:
        """Name of the search, as declared in the manifest."""
        return self.manifest.name

    @property
    def model(self) -> str:
        """Requested Ollama model."""
        return self.manifest.model


def manifest_hash(source: str) -> Sha256:
    """Computes the checksum of a manifest from its source text.

    Line endings are normalized before hashing: the same manifest must produce the same
    checksum whether it was fetched on Windows or on Linux. Nothing else is normalized —
    an edited comment does change the checksum, and that is intentional: it is preferable
    to create a separate run rather than risk reusing results from a different version of
    the file.
    """
    normalized = source.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load(path: str | Path) -> LoadedManifest:
    """Reads, validates and hashes a search manifest.

    Args:
        path: path to the YAML file.

    Returns:
        The validated manifest, its source text and its checksum.

    Raises:
        ManifestError: missing file, malformed YAML, or invalid manifest.
    """
    manifest_path = Path(path)

    try:
        source = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        message = f"unreadable manifest: {manifest_path} ({exc})"
        raise ManifestError(message) from exc

    try:
        # `safe_load` does not instantiate any Python object: a manifest remains data.
        # The result is deliberately treated as `object`, then narrowed by pydantic.
        raw: object = yaml.safe_load(source)
    except yaml.YAMLError as exc:
        message = f"malformed YAML in {manifest_path}: {exc}"
        raise ManifestError(message) from exc

    if not isinstance(raw, dict):
        kind = type(raw).__name__
        message = f"{manifest_path} must contain a YAML mapping at the root, found: {kind}"
        raise ManifestError(message)

    try:
        manifest = SearchManifest.model_validate(raw)
    except ValidationError as exc:
        message = f"invalid manifest ({manifest_path}):\n{exc}"
        raise ManifestError(message) from exc

    return LoadedManifest(
        manifest=manifest,
        path=manifest_path,
        source=source,
        hash=manifest_hash(source),
    )
