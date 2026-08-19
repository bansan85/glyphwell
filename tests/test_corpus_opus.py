"""Résolution dans l'index OPUS et téléchargement de l'archive, hors réseau.

Aucun test ne sort de la machine : `httpx.MockTransport` est injecté par le paramètre
`client`, déjà présent dans les signatures. Rien à monkeypatcher.
"""

import hashlib
from pathlib import Path

import httpx
import pytest

from glyphwell.corpus.opus import (
    _version_key,
    download_corpus,
    iter_available_versions,
    resolve_archive,
)
from glyphwell.errors import CorpusError, MetadataError
from glyphwell.types import JsonObject

ARCHIVE_URL = "https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/raw/en.zip"
ARCHIVE_NAME = "OpenSubtitles_v2018_raw_en.zip"
PAYLOAD = bytes(range(256)) * 8
"""2048 octets, soit exactement les 2 kilo-octets annoncés par l'index de test."""


def _record(**overrides: str | int) -> JsonObject:
    """Un enregistrement de l'index, dans la forme rendue par l'API OPUS."""
    record: JsonObject = {
        "corpus": "OpenSubtitles",
        "version": "v2018",
        "preprocessing": "raw",
        "source": "en",
        "target": "",
        "url": ARCHIVE_URL,
        "size": len(PAYLOAD) // 1024,
        "documents": 1,
    }
    record.update(overrides)
    return record


def _client(
    *,
    records: list[JsonObject] | None = None,
    payload: bytes = PAYLOAD,
    index_status: int = 200,
    seen: list[httpx.Request] | None = None,
) -> httpx.Client:
    """Client servant l'index puis l'archive, et notant les requêtes reçues."""
    served = [_record()] if records is None else records

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)

        if "opusapi" in str(request.url):
            if index_status != 200:
                return httpx.Response(index_status, text="indisponible")
            return httpx.Response(200, json={"corpora": served})

        requested = request.headers.get("Range")
        if requested is None:
            return httpx.Response(200, content=payload)

        start = int(requested.removeprefix("bytes=").rstrip("-"))
        if start >= len(payload):
            return httpx.Response(416)
        return httpx.Response(
            206,
            content=payload[start:],
            headers={"Content-Range": f"bytes {start}-{len(payload) - 1}/{len(payload)}"},
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolve_picks_the_monolingual_record() -> None:
    """Interroger une langue ramène aussi ses paires bilingues : il faut les écarter."""
    with _client(records=[_record(target="fr"), _record()]) as http:
        record = resolve_archive(client=http)

    assert record.target == ""
    assert record.url == ARCHIVE_URL


def test_other_languages_monolingual_archives_are_ignored() -> None:
    """En préprocessing ``raw``, l'index rend l'archive mono de *chaque* langue appariée.

    Sans test sur `source`, une requête ``en`` remonte une cinquantaine de candidats et le
    premier venu — ``eo``, ``es``... — serait téléchargé à la place du bon.
    """
    records = [
        _record(source="eo", url="https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/raw/eo.zip"),
        _record(source="es", url="https://object.pouta.csc.fi/OPUS-OpenSubtitles/v2018/raw/es.zip"),
        _record(),
    ]
    with _client(records=records) as http:
        record = resolve_archive(client=http)

    assert record.source == "en"
    assert record.url == ARCHIVE_URL


def test_missing_record_lists_what_the_index_offers() -> None:
    """L'erreur doit dire quoi corriger : version ou langue."""
    with (
        _client(records=[_record(version="v2024", target="fr")]) as http,
        pytest.raises(CorpusError, match="v2024"),
    ):
        resolve_archive(client=http)


def test_empty_index_is_reported() -> None:
    with _client(records=[]) as http, pytest.raises(CorpusError, match="aucun enregistrement"):
        resolve_archive(client=http)


def test_unreachable_index_is_reported() -> None:
    with _client(index_status=503) as http, pytest.raises(MetadataError, match="injoignable"):
        resolve_archive(client=http)


def test_versions_are_listed_newest_first() -> None:
    records = [_record(version=version) for version in ("v1", "v2024", "v2018")]
    with _client(records=records) as http:
        assert list(iter_available_versions(client=http)) == ["v2024", "v2018", "v1"]


def test_versions_query_omits_the_version_parameter() -> None:
    """Un ``version=`` vide fait rendre zéro résultat à l'index : il faut l'omettre.

    Le code d'`opustools` suggère qu'une espace sert de joker ; l'API en ligne, non.
    """
    seen: list[httpx.Request] = []
    with _client(records=[_record()], seen=seen) as http:
        list(iter_available_versions(client=http))

    assert "version=" not in str(seen[0].url)


def test_version_key_orders_numerically() -> None:
    """Un tri lexicographique classerait ``v9`` après ``v2018``."""
    assert _version_key("v9") < _version_key("v2018")
    assert _version_key("latest") == ()


def test_download_writes_archive_and_hashes_it(tmp_path: Path) -> None:
    seen: list[tuple[int, int | None]] = []

    with _client() as http:
        result = download_corpus(
            dest_dir=tmp_path / "corpus",
            progress=lambda received, total: seen.append((received, total)),
            client=http,
        )

    assert result.archive_path == tmp_path / "corpus" / ARCHIVE_NAME
    assert result.archive_path.read_bytes() == PAYLOAD
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()
    assert result.version == "v2018"
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))


def test_no_part_file_survives_a_complete_download(tmp_path: Path) -> None:
    """Un ``.part`` résiduel ferait croire à une reprise possible sur un fichier complet."""
    with _client() as http:
        download_corpus(dest_dir=tmp_path, client=http)

    assert [path.name for path in tmp_path.iterdir()] == [ARCHIVE_NAME]


def test_download_resumes_from_an_interrupted_part(tmp_path: Path) -> None:
    """Le cœur du choix de `httpx` : ne pas retélécharger 30 Go après une coupure."""
    part = tmp_path / f"{ARCHIVE_NAME}.part"
    part.write_bytes(PAYLOAD[:512])
    seen: list[httpx.Request] = []

    with _client(seen=seen) as http:
        result = download_corpus(dest_dir=tmp_path, client=http)

    ranges = [request.headers["Range"] for request in seen if "Range" in request.headers]
    assert ranges == ["bytes=512-"]
    assert result.archive_path.read_bytes() == PAYLOAD
    # Les octets déjà présents n'ont pas traversé le hachage : pas d'empreinte inventée.
    assert result.sha256 is None


def test_resume_reports_progress_from_the_existing_offset(tmp_path: Path) -> None:
    """Une barre repartant de zéro mentirait sur ce qui reste à faire."""
    (tmp_path / f"{ARCHIVE_NAME}.part").write_bytes(PAYLOAD[:512])
    seen: list[tuple[int, int | None]] = []

    with _client() as http:
        download_corpus(
            dest_dir=tmp_path,
            progress=lambda received, total: seen.append((received, total)),
            client=http,
        )

    assert seen[0] == (512, len(PAYLOAD))
    assert seen[-1] == (len(PAYLOAD), len(PAYLOAD))


def test_existing_archive_is_left_alone(tmp_path: Path) -> None:
    archive = tmp_path / ARCHIVE_NAME
    archive.write_bytes(PAYLOAD)
    seen: list[httpx.Request] = []

    with _client(seen=seen) as http:
        result = download_corpus(dest_dir=tmp_path, client=http)

    assert [str(request.url) for request in seen if "opusapi" not in str(request.url)] == []
    assert result.sha256 is None
    assert archive.read_bytes() == PAYLOAD


def test_force_downloads_again(tmp_path: Path) -> None:
    archive = tmp_path / ARCHIVE_NAME
    archive.write_bytes(b"archive perimee")

    with _client() as http:
        result = download_corpus(dest_dir=tmp_path, force=True, client=http)

    assert archive.read_bytes() == PAYLOAD
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_force_ignores_a_stale_part(tmp_path: Path) -> None:
    """`--force` sert à repartir de zéro : reprendre un ``.part`` douteux irait contre."""
    (tmp_path / f"{ARCHIVE_NAME}.part").write_bytes(b"debut douteux")
    seen: list[httpx.Request] = []

    with _client(seen=seen) as http:
        result = download_corpus(dest_dir=tmp_path, force=True, client=http)

    assert not [request for request in seen if "Range" in request.headers]
    assert result.archive_path.read_bytes() == PAYLOAD
