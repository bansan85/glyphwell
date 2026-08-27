"""Loading, validation and hashing of manifests."""

from pathlib import Path

import pytest

from glyphwell.errors import ManifestError
from glyphwell.manifest import load, manifest_hash
from glyphwell.manifest.model import PrefilterMode


def test_loads_minimal_manifest(minimal_manifest: Path) -> None:
    loaded = load(minimal_manifest)
    assert loaded.name == "minimal"
    assert loaded.model == "test-model"
    assert len(loaded.hash) == 64


def test_loads_example_manifest(example_manifest: Path) -> None:
    """The shipped template must stay valid: it is the executable documentation of the format."""
    loaded = load(example_manifest)
    assert loaded.manifest.chunk.overlap == 12
    assert loaded.manifest.prefilter.mode is PrefilterMode.OFF
    assert loaded.manifest.output.json_schema is not None
    assert loaded.manifest.match_when == "matched"


def test_hash_is_stable_and_line_ending_agnostic() -> None:
    """The same manifest must give the same checksum on Windows and on Linux."""
    source = "name: a\nmodel: m\nprompt:\n  user: x\n"
    assert manifest_hash(source) == manifest_hash(source.replace("\n", "\r\n"))


def test_hash_changes_with_content() -> None:
    """Editing the manifest must create a new run, not reuse the old one."""
    base = "name: a\nmodel: m\nprompt:\n  user: x\n"
    assert manifest_hash(base) != manifest_hash(base.replace("user: x", "user: y"))


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="unreadable"):
        load(tmp_path / "absent.yaml")


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """A misspelled key must not turn into a filter that is silently ignored."""
    path = tmp_path / "typo.yaml"
    path.write_text("name: a\nmodel: m\nprompt:\n  user: x\nchnk:\n  size: 10\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="invalid"):
        load(path)


def test_missing_num_ctx_is_rejected(tmp_path: Path) -> None:
    """Chunk sizing is derived from num_ctx/num_predict: neither can be silently absent."""
    path = tmp_path / "no-num-ctx.yaml"
    path.write_text(
        "name: a\nmodel: m\noptions:\n  num_predict: 256\nprompt:\n  user: x\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="num_ctx"):
        load(path)


def test_missing_num_predict_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "no-num-predict.yaml"
    path.write_text(
        "name: a\nmodel: m\noptions:\n  num_ctx: 4096\nprompt:\n  user: x\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="num_predict"):
        load(path)


@pytest.mark.parametrize(
    "yaml_value",
    ['"1024"', "1.5", "true", "0", "-1"],
    ids=["string", "float", "bool", "zero", "negative"],
)
def test_invalid_num_ctx_is_rejected(tmp_path: Path, yaml_value: str) -> None:
    """A non-int (string, float, bool) or a non-positive int must fail validation."""
    path = tmp_path / "bad-num-ctx.yaml"
    path.write_text(
        f"name: a\nmodel: m\noptions:\n  num_ctx: {yaml_value}\n  num_predict: 256\n"
        "prompt:\n  user: x\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="num_ctx"):
        load(path)


def test_active_prefilter_requires_patterns(tmp_path: Path) -> None:
    path = tmp_path / "bad-prefilter.yaml"
    path.write_text(
        "name: a\nmodel: m\nprompt:\n  user: x\nprefilter:\n  mode: any\n  patterns: []\n",
        encoding="utf-8",
    )
    with pytest.raises(ManifestError, match="pattern"):
        load(path)


def test_non_mapping_root_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="YAML mapping"):
        load(path)
