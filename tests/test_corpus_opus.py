"""Resolution in the OPUS index and archive download, without touching the network.

No test leaves the machine: `httpx.MockTransport` is injected via the `client` parameter,
already present in the signatures. Nothing to monkeypatch.
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
"""2048 bytes, exactly the 2 kilobytes announced by the test index."""


def _record(**overrides: str | int) -> JsonObject:
    """A record from the index, in the shape returned by the OPUS API."""
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
    """Client serving the index then the archive, and recording the requests received."""
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
    """Querying a language also returns its bilingual pairs: they must be discarded."""
    with _client(records=[_record(target="fr"), _record()]) as http:
        record = resolve_archive(client=http)

    assert record.target == ""
    assert record.url == ARCHIVE_URL


def test_other_languages_monolingual_archives_are_ignored() -> None:
    """In ``raw`` preprocessing, the index returns the monolingual archive of *every*
    language paired with ours.

    Without a check on `source`, an ``en`` request surfaces some fifty candidates and
    whichever comes first — ``eo``, ``es``... — would be downloaded instead of the right
    one.
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
    """The error must say what to fix: version or language."""
    with (
        _client(records=[_record(version="v2024", target="fr")]) as http,
        pytest.raises(CorpusError, match="v2024"),
    ):
        resolve_archive(client=http)


def test_empty_index_is_reported() -> None:
    with _client(records=[]) as http, pytest.raises(CorpusError, match="no records"):
        resolve_archive(client=http)


def test_unreachable_index_is_reported() -> None:
    with _client(index_status=503) as http, pytest.raises(MetadataError, match="unreachable"):
        resolve_archive(client=http)


def test_versions_are_listed_newest_first() -> None:
    records = [_record(version=version) for version in ("v1", "v2024", "v2018")]
    with _client(records=records) as http:
        assert list(iter_available_versions(client=http)) == ["v2024", "v2018", "v1"]


def test_versions_query_omits_the_version_parameter() -> None:
    """An empty ``version=`` makes the index return zero results: it must be omitted.

    `opustools`'s code suggests that a single space acts as a wildcard; the online API
    disagrees.
    """
    seen: list[httpx.Request] = []
    with _client(records=[_record()], seen=seen) as http:
        list(iter_available_versions(client=http))

    assert "version=" not in str(seen[0].url)


def test_version_key_orders_numerically() -> None:
    """A lexicographic sort would rank ``v9`` after ``v2018``."""
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
    """A leftover ``.part`` would suggest a resume is possible on a complete file."""
    with _client() as http:
        download_corpus(dest_dir=tmp_path, client=http)

    assert [path.name for path in tmp_path.iterdir()] == [ARCHIVE_NAME]


def test_download_resumes_from_an_interrupted_part(tmp_path: Path) -> None:
    """The core reason for choosing `httpx`: not re-downloading 30 GB after a cutoff."""
    part = tmp_path / f"{ARCHIVE_NAME}.part"
    part.write_bytes(PAYLOAD[:512])
    seen: list[httpx.Request] = []

    with _client(seen=seen) as http:
        result = download_corpus(dest_dir=tmp_path, client=http)

    ranges = [request.headers["Range"] for request in seen if "Range" in request.headers]
    assert ranges == ["bytes=512-"]
    assert result.archive_path.read_bytes() == PAYLOAD
    # The bytes already present never went through hashing: no checksum is invented.
    assert result.sha256 is None


def test_resume_reports_progress_from_the_existing_offset(tmp_path: Path) -> None:
    """A progress bar restarting from zero would lie about what remains to be done."""
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
    archive.write_bytes(b"stale archive")

    with _client() as http:
        result = download_corpus(dest_dir=tmp_path, force=True, client=http)

    assert archive.read_bytes() == PAYLOAD
    assert result.sha256 == hashlib.sha256(PAYLOAD).hexdigest()


def test_force_ignores_a_stale_part(tmp_path: Path) -> None:
    """`--force` exists to start over: resuming a dubious ``.part`` would defeat that."""
    (tmp_path / f"{ARCHIVE_NAME}.part").write_bytes(b"dubious start")
    seen: list[httpx.Request] = []

    with _client(seen=seen) as http:
        result = download_corpus(dest_dir=tmp_path, force=True, client=http)

    assert not [request for request in seen if "Range" in request.headers]
    assert result.archive_path.read_bytes() == PAYLOAD
