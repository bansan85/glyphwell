"""The `--no-check-certificate` escape hatch, from the CLI down to the HTTP client.

Nothing leaves the machine: the client the command would have built is replaced by one
backed by an `httpx.MockTransport`, which is also what records the `verify` asked for.
`glyphwell metadata fetch-imdb` is the vehicle, but the wiring under test — root option,
`Settings.verify_tls`, `glyphwell.http.make_client` — is shared with `corpus fetch`.
"""

from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from glyphwell.cli import app
from glyphwell.config import Settings
from glyphwell.http import DEFAULT_TIMEOUT

runner = CliRunner()

PAYLOAD = b"gzip-bytes"


@pytest.fixture
def verify_calls(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Records the `verify` of every client the CLI builds, serving canned bytes."""
    seen: list[bool] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PAYLOAD)

    def fake_make_client(*, timeout: float = DEFAULT_TIMEOUT, verify: bool = True) -> httpx.Client:
        seen.append(verify)
        return httpx.Client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr("glyphwell.cli.metadata.make_client", fake_make_client)
    return seen


def _fetch(tmp_path: Path, *options: str) -> None:
    result = runner.invoke(app, ["--data-dir", str(tmp_path), *options, "metadata", "fetch-imdb"])
    assert result.exit_code == 0, result.output


def test_settings_verify_tls_defaults_to_true() -> None:
    """`_env_file=None`: the machine's local `.env` must not decide this."""
    assert Settings(_env_file=None).verify_tls is True


def test_verification_stays_on_without_the_flag(
    tmp_path: Path, verify_calls: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLYPHWELL_VERIFY_TLS", "true")

    _fetch(tmp_path)

    assert verify_calls == [True]
    assert (tmp_path / "downloads" / "title.basics.tsv.gz").read_bytes() == PAYLOAD


def test_flag_disables_verification_over_the_environment(
    tmp_path: Path, verify_calls: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit `--no-check-certificate` wins: the flag can only ever loosen."""
    monkeypatch.setenv("GLYPHWELL_VERIFY_TLS", "true")

    _fetch(tmp_path, "--no-check-certificate")

    assert verify_calls == [False]
    assert (tmp_path / "downloads" / "title.basics.tsv.gz").read_bytes() == PAYLOAD


def test_environment_can_disable_verification(
    tmp_path: Path, verify_calls: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GLYPHWELL_VERIFY_TLS", "false")

    _fetch(tmp_path)

    assert verify_calls == [False]
