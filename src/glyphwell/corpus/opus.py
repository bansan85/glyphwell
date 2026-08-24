"""Acquisition du corpus via `opustools`.

`opustools` expose `OpusGet`, qui connaît le contrat de l'index OPUS : forme de l'URL,
paramètres, nommage des archives. C'est à ce titre qu'il est utilisé ici — pour *trouver*
l'archive. On cible le corpus ``OpenSubtitles``, une langue unique et le préprocessing
``raw`` : c'est la seule variante qui conserve le texte non tokenisé, exploitable tel quel
par un LLM.

Le transfert des octets, lui, passe par `httpx` et non par `OpusGet.get_files()`. Ce
dernier est inutilisable sur plusieurs dizaines de Go : il n'a pas de délai d'attente, ne
sait pas reprendre, avale `urllib.error.URLError` pour se contenter d'un `print` — et il
écrit directement sous le nom définitif. Une coupure à 90 % laisserait donc une archive
tronquée que rien ne distingue d'une archive complète. Ici, le transfert va dans un fichier
``.part`` repris par en-tête ``Range``, renommé seulement une fois terminé.

L'archive n'est jamais décompressée : cf. `glyphwell.corpus.archive`.
"""

import hashlib
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

import httpx
from opustools import OpusGet
from pydantic import BaseModel, ConfigDict, ValidationError

from glyphwell.errors import CorpusError, MetadataError
from glyphwell.logging import get_logger
from glyphwell.types import LanguageCode, OpusVersion, Sha256

__all__ = [
    "DEFAULT_CORPUS",
    "DEFAULT_PREPROCESSING",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VERSION",
    "CorpusDownload",
    "OpusFileRecord",
    "Preprocessing",
    "ProgressCallback",
    "download_corpus",
    "iter_available_versions",
    "resolve_archive",
]

_log = get_logger(__name__)

type Preprocessing = Literal["raw", "xml", "mono"]

type ProgressCallback = Callable[[int, int | None], None]
"""Rappel de progression : octets reçus au total, taille finale ou `None` si inconnue.

Les octets reçus incluent ce qui l'avait déjà été lors d'une tentative précédente : sur une
reprise, la progression repart de l'offset du ``.part``, pas de zéro.
"""

DEFAULT_CORPUS: Final = "OpenSubtitles"
DEFAULT_VERSION: Final[OpusVersion] = "v2024"
DEFAULT_PREPROCESSING: Final[Preprocessing] = "raw"
"""``raw`` conserve le texte non tokenisé ; ``xml`` le découpe en balises ``<w>``."""

DEFAULT_TIMEOUT: Final = 60.0
"""Délai d'attente, en secondes, appliqué par bloc et non au transfert entier."""

_PART_SUFFIX: Final = ".part"
_CHUNK_SIZE: Final = 1 << 20
_KIB: Final = 1024
"""L'index OPUS exprime `size` en kilo-octets (cf. `OpusGet.format_size`)."""

_OMITTED: Final = ""
"""`OpusGet` n'émet pas les paramètres vides, et c'est la seule façon de dire « toutes
les valeurs ». Le joker « une espace » que suggère son code produit ``version=``, que
l'API en ligne interprète comme « aucune version » : elle renvoie alors zéro résultat."""

_SIZE_TOLERANCE: Final = 0.01
"""La taille annoncée par l'index est arrondie : au-delà de 1 % d'écart, on avertit."""


@dataclass(frozen=True, slots=True, kw_only=True)
class CorpusDownload:
    """Résultat d'un téléchargement de corpus."""

    corpus: str
    version: OpusVersion
    language: LanguageCode
    archive_path: Path
    sha256: Sha256 | None
    url: str | None


class OpusFileRecord(BaseModel):
    """Un enregistrement de l'index OPUS.

    `extra="ignore"`, à l'inverse des manifestes : l'API n'est pas sous notre contrôle, un
    champ ajouté en amont ne doit pas faire échouer un téléchargement.

    Attributes:
        target: vide pour une archive monolingue. C'est le discriminant : une requête sur
            une langue renvoie aussi les paires bilingues qui la contiennent.
        size: taille en **kilo-octets**, arrondie.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    corpus: str
    version: OpusVersion
    preprocessing: str
    source: LanguageCode
    target: str
    url: str
    size: int


class _OpusIndex(BaseModel):
    """Enveloppe de la réponse de l'index."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    corpora: tuple[OpusFileRecord, ...]


def _make_client(*, timeout: float = DEFAULT_TIMEOUT) -> httpx.Client:
    """Client HTTP par défaut.

    `follow_redirects` est indispensable : l'index renvoie une URL de stockage objet qui
    redirige.
    """
    return httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout, connect=timeout),
    )


def _opus_getter(
    *,
    corpus: str | None = None,
    version: str | None = None,
    language: LanguageCode | None = None,
    preprocessing: str | None = None,
) -> OpusGet:
    """Instancie `OpusGet` sans effet de bord.

    `download_dir` reste le répertoire courant : `OpusGet` le crée s'il manque, et on ne
    veut pas qu'une simple construction d'URL crée un répertoire. Rien n'est téléchargé
    par cette instance — seuls `url` et `make_file_name` sont lus.

    Attention à l'ordre des paramètres d'`OpusGet` : `directory` est le nom du corpus,
    `source` la langue.
    """
    return OpusGet(
        source=language,
        directory=corpus,
        release=version if version is not None else _OMITTED,
        preprocess=preprocessing if preprocessing is not None else _OMITTED,
        download_dir=".",
        suppress_prompts=True,
    )


def _index_url(
    *,
    corpus: str | None = None,
    version: str | None = None,
    language: LanguageCode | None = None,
    preprocessing: str | None = None,
) -> str:
    """URL de l'index OPUS pour ces critères."""
    # `OpusGet` construit l'URL avec un `&` final, que son propre code retire à l'appel.
    return _opus_getter(
        corpus=corpus,
        version=version,
        language=language,
        preprocessing=preprocessing,
    ).url.removesuffix("&")


def _fetch_records(url: str, *, client: httpx.Client | None = None) -> tuple[OpusFileRecord, ...]:
    """Interroge l'index et valide sa réponse.

    Raises:
        MetadataError: index injoignable, ou réponse illisible.
    """
    owned = client is None
    http = client if client is not None else _make_client()
    try:
        response = http.get(url)
        response.raise_for_status()
        # Frontière non typée : `object`, puis resserrement immédiat par pydantic.
        payload: object = response.json()
    except httpx.HTTPError as exc:
        message = f"index OPUS injoignable ({url}) : {exc}"
        raise MetadataError(message) from exc
    except ValueError as exc:
        message = f"réponse illisible de l'index OPUS ({url}) : {exc}"
        raise MetadataError(message) from exc
    finally:
        if owned:
            http.close()

    try:
        index = _OpusIndex.model_validate(payload)
    except ValidationError as exc:
        message = f"réponse inattendue de l'index OPUS ({url}) :\n{exc}"
        raise MetadataError(message) from exc

    _log.debug("index OPUS : %d enregistrement(s) pour %s", len(index.corpora), url)
    return index.corpora


def _version_key(version: OpusVersion) -> tuple[int, ...]:
    """Clé de tri numérique d'une release : ``v2018`` donne ``(2018,)``.

    Une version non numérique donne une clé vide, donc se classe en dernier au tri
    décroissant ; l'appelant départage sur la chaîne elle-même.
    """
    parts = version.removeprefix("v").split(".")
    if not all(part.isdigit() for part in parts):
        return ()
    return tuple(int(part) for part in parts)


def iter_available_versions(
    corpus: str = DEFAULT_CORPUS,
    *,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    client: httpx.Client | None = None,
) -> Iterator[OpusVersion]:
    """Liste les versions disponibles d'un corpus, de la plus récente à la plus ancienne.

    Alimente la détection de fraîcheur : une release supérieure à celle déjà en base
    signifie que des sous-titres plus récents sont disponibles.

    La langue et le préprocessing sont fixés à dessein. Sans eux, l'index renverrait toutes
    les paires de langues du corpus — pour OpenSubtitles, plusieurs milliers
    d'enregistrements pour une information qui tient en quelques lignes.

    Args:
        corpus: nom du corpus OPUS.
        language: langue dont on veut les releases.
        preprocessing: variante de préprocessing.
        client: client HTTP à réutiliser, sinon un client jetable est créé.

    Yields:
        Les versions, de la plus récente à la plus ancienne.

    Raises:
        MetadataError: l'index OPUS est injoignable ou illisible.
    """
    # Aucun paramètre `version` : c'est ce qui fait rendre à l'index toutes les releases.
    url = _index_url(corpus=corpus, language=language, preprocessing=preprocessing)
    versions = {record.version for record in _fetch_records(url, client=client)}
    yield from sorted(versions, key=lambda version: (_version_key(version), version), reverse=True)


def resolve_archive(
    *,
    corpus: str = DEFAULT_CORPUS,
    version: OpusVersion = DEFAULT_VERSION,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    client: httpx.Client | None = None,
) -> OpusFileRecord:
    """Retrouve dans l'index l'archive monolingue correspondant à ces critères.

    Séparée de `download_corpus` pour que l'appelant puisse annoncer l'URL et la taille
    avant d'engager un transfert de plusieurs dizaines de Go.

    Args:
        corpus: nom du corpus OPUS.
        version: release visée.
        language: code de langue.
        preprocessing: variante de préprocessing.
        client: client HTTP à réutiliser.

    Returns:
        L'enregistrement de l'archive monolingue.

    Raises:
        MetadataError: l'index est injoignable ou illisible.
        CorpusError: l'index ne propose aucune archive pour ces critères.
    """
    url = _index_url(
        corpus=corpus,
        version=version,
        language=language,
        preprocessing=preprocessing,
    )
    records = _fetch_records(url, client=client)
    # Deux familles à écarter, et l'index les renvoie toutes les deux : les paires
    # bilingues contenant la langue demandée (`target` non vide), et — en préprocessing
    # ``raw`` — l'archive monolingue de *chaque* langue appariée à la nôtre. Sans le test
    # sur `source`, une requête ``en`` remonte une cinquantaine de candidats dont ``eo``
    # ou ``es``, et le premier venu serait téléchargé.
    monolingual = [record for record in records if not record.target and record.source == language]

    if not monolingual:
        message = (
            f"aucune archive monolingue {corpus} {version} {language} ({preprocessing})"
            f" dans l'index OPUS. {_describe(records)}"
        )
        raise CorpusError(message)

    if len(monolingual) > 1:
        _log.warning(
            "%d archives monolingues correspondent ; la première est retenue : %s",
            len(monolingual),
            monolingual[0].url,
        )
    return monolingual[0]


def _describe(records: tuple[OpusFileRecord, ...], *, limit: int = 12) -> str:
    """Décrit ce que l'index a renvoyé, pour rendre l'erreur actionnable.

    Une requête large ramène des centaines d'enregistrements : on résume par les deux axes
    sur lesquels l'appelant peut agir, la version et la langue.
    """
    if not records:
        return "L'index n'a renvoyé aucun enregistrement : vérifier le nom du corpus."

    versions = sorted({record.version for record in records})
    languages = sorted({record.source for record in records if not record.target})
    shown = ", ".join(languages[:limit])
    suffix = f", ... ({len(languages)} au total)" if len(languages) > limit else ""
    return f"Versions présentes : {', '.join(versions)}. Langues monolingues : {shown}{suffix}."


def _archive_name(record: OpusFileRecord) -> str:
    """Nom local de l'archive, tel qu'`opustools` le déduit de l'URL.

    L'instance est construite avec la version *concrète* de l'enregistrement : avec
    ``release='latest'``, `make_file_name` remplacerait la version par ``latest`` dans le
    nom, et l'archive perdrait la trace de la release qu'elle contient.
    """
    getter = _opus_getter(version=record.version)
    fields: Mapping[str, str] = {"url": record.url, "version": record.version}
    return Path(getter.make_file_name(fields)).name


def _total_size(response: httpx.Response, resume_from: int) -> int | None:
    """Taille finale de l'archive, déduite des en-têtes.

    Sur une reprise, ``Content-Length`` ne décrit que le reliquat : c'est ``Content-Range``
    qui porte le total. Sans lui, on additionne l'offset déjà acquis.
    """
    content_range = response.headers.get("Content-Range", "")
    if "/" in content_range:
        declared = content_range.rsplit("/", 1)[1]
        if declared.isdigit():
            return int(declared)

    length = response.headers.get("Content-Length", "")
    if length.isdigit():
        return resume_from + int(length)
    return None


def _stream_to_file(
    url: str,
    *,
    archive_path: Path,
    force: bool,
    progress: ProgressCallback | None,
    client: httpx.Client | None,
) -> Sha256 | None:
    """Télécharge `url` vers `archive_path`, en reprenant un ``.part`` existant.

    Returns:
        L'empreinte de l'archive quand le transfert est parti de zéro — le calcul est alors
        gratuit, fait au fil de l'eau. `None` après une reprise : les octets déjà présents
        n'ont pas traversé le hachage, et une passe complète sur des dizaines de Go ne se
        décide pas toute seule.

    Raises:
        CorpusError: transfert interrompu ou écriture impossible.
    """
    part = archive_path.with_name(archive_path.name + _PART_SUFFIX)
    resume_from = part.stat().st_size if part.is_file() and not force else 0
    headers = {"Range": f"bytes={resume_from}-"} if resume_from else {}
    if resume_from:
        _log.info("reprise du téléchargement à %d octets : %s", resume_from, part.name)

    owned = client is None
    http = client if client is not None else _make_client()
    digest = hashlib.sha256()
    hashed = True

    try:
        with http.stream("GET", url, headers=headers) as response:
            if resume_from and response.status_code == httpx.codes.REQUESTED_RANGE_NOT_SATISFIABLE:
                _log.warning(
                    "le serveur juge le ``.part`` complet (416) : %s est renommé tel quel,"
                    " la vérification de l'archive tranchera",
                    part.name,
                )
                part.replace(archive_path)
                return None

            if resume_from and response.status_code != httpx.codes.PARTIAL_CONTENT:
                _log.warning("le serveur ignore l'en-tête Range : téléchargement repris de zéro")
                resume_from = 0

            response.raise_for_status()
            total = _total_size(response, resume_from)
            received = resume_from
            hashed = resume_from == 0
            if progress is not None:
                progress(received, total)

            with part.open("ab" if resume_from else "wb") as handle:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    handle.write(chunk)
                    if hashed:
                        digest.update(chunk)
                    received += len(chunk)
                    if progress is not None:
                        progress(received, total)
    except httpx.HTTPError as exc:
        message = (
            f"téléchargement interrompu ({url}) : {exc}. Le fichier {part.name} est conservé,"
            " un nouvel appel reprendra où il s'est arrêté."
        )
        raise CorpusError(message) from exc
    except OSError as exc:
        message = f"écriture impossible dans {part} : {exc}"
        raise CorpusError(message) from exc
    finally:
        if owned:
            http.close()

    # Renommage en dernier : tant qu'il n'a pas eu lieu, une archive incomplète ne peut pas
    # être prise pour une archive complète.
    part.replace(archive_path)
    return digest.hexdigest() if hashed else None


def download_corpus(
    *,
    dest_dir: Path,
    corpus: str = DEFAULT_CORPUS,
    version: OpusVersion = DEFAULT_VERSION,
    language: LanguageCode = "en",
    preprocessing: Preprocessing = DEFAULT_PREPROCESSING,
    force: bool = False,
    record: OpusFileRecord | None = None,
    progress: ProgressCallback | None = None,
    client: httpx.Client | None = None,
) -> CorpusDownload:
    """Télécharge l'archive monolingue d'un corpus OPUS.

    L'archive est déposée telle quelle : elle n'est pas décompressée, elle *est* le corpus.

    Args:
        dest_dir: répertoire où déposer l'archive.
        corpus: nom du corpus OPUS.
        version: release visée.
        language: code de langue.
        preprocessing: variante de préprocessing.
        force: re-télécharge même si l'archive est déjà présente.
        record: enregistrement déjà résolu, pour éviter un second appel à l'index.
        progress: rappel de progression.
        client: client HTTP à réutiliser.

    Returns:
        La description de l'archive obtenue.

    Raises:
        MetadataError: l'index OPUS est injoignable.
        CorpusError: téléchargement impossible ou archive incomplète.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    if record is None:
        record = resolve_archive(
            corpus=corpus,
            version=version,
            language=language,
            preprocessing=preprocessing,
            client=client,
        )

    archive_path = dest_dir / _archive_name(record)
    announced = record.size * _KIB
    # `debug` et non `info` : la CLI annonce déjà l'URL retenue avant d'engager le
    # transfert, et la répéter en journal ne ferait que doubler la même ligne.
    _log.debug("archive OPUS : %s (%d octets annoncés)", record.url, announced)

    if archive_path.is_file() and not force:
        _warn_on_size_mismatch(archive_path, announced=announced)
        _log.info("archive déjà présente, téléchargement ignoré : %s", archive_path)
        sha256 = None
    else:
        sha256 = _stream_to_file(
            record.url,
            archive_path=archive_path,
            force=force,
            progress=progress,
            client=client,
        )

    return CorpusDownload(
        corpus=record.corpus,
        version=record.version,
        language=record.source,
        archive_path=archive_path,
        sha256=sha256,
        url=record.url,
    )


def _warn_on_size_mismatch(archive_path: Path, *, announced: int) -> None:
    """Signale une archive dont la taille s'écarte de ce que l'index annonce."""
    if not announced:
        return
    actual = archive_path.stat().st_size
    if abs(actual - announced) > announced * _SIZE_TOLERANCE:
        _log.warning(
            "%s fait %d octets, l'index en annonce ~%d : archive probablement incomplète."
            " Relancer avec --force.",
            archive_path.name,
            actual,
            announced,
        )
