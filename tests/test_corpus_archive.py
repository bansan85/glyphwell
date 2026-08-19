"""L'archive se lit membre par membre, sans jamais être décompressée."""

import zipfile
from pathlib import Path

import pytest

from glyphwell.corpus.archive import CorpusArchive
from glyphwell.errors import CorpusError

SUBTITLE = "OpenSubtitles/raw/en/1999/0133093/3660124.xml"


def test_iter_members_keeps_only_subtitles(sample_archive: Path) -> None:
    """Répertoires et fichiers étrangers ne doivent pas entrer dans le catalogue."""
    with CorpusArchive(sample_archive) as archive:
        members = list(archive.iter_members())

    assert [member.rel_path for member in members] == [SUBTITLE]
    assert members[0].size > 0


def test_open_member_reads_without_writing_anything(sample_archive: Path) -> None:
    """Le contrat du projet : lire le corpus ne produit aucun fichier sur le disque."""
    before = set(sample_archive.parent.iterdir())

    with CorpusArchive(sample_archive) as archive, archive.open_member(SUBTITLE) as stream:
        content = stream.read().decode("utf-8")

    assert "<document" in content
    assert set(sample_archive.parent.iterdir()) == before


def test_member_name_is_its_own_open_key(sample_archive: Path) -> None:
    """`rel_path` doit rester utilisable tel quel : aucune normalisation ne s'y applique."""
    with CorpusArchive(sample_archive) as archive:
        member = next(iter(archive.iter_members()))
        with archive.open_member(member.rel_path) as stream:
            assert stream.read()


def test_summarize_signals_unexpected_members(sample_archive: Path) -> None:
    """Un membre à l'extension imprévue est compté, pas absorbé en silence."""
    with CorpusArchive(sample_archive) as archive:
        summary = archive.summarize()

    assert summary.subtitle_count == 1
    assert summary.samples == (SUBTITLE,)
    assert summary.unexpected_count == 1
    assert summary.unexpected_samples == ("OpenSubtitles/raw/en/1999/0133093/3660125.xml.gz",)


def test_service_files_are_not_an_alert(sample_archive: Path) -> None:
    """INFO / README / LICENSE sont dans toute archive OPUS : les signaler serait du bruit."""
    with CorpusArchive(sample_archive) as archive:
        summary = archive.summarize()

    assert summary.metadata_count == 1
    assert "OpenSubtitles/README" not in summary.unexpected_samples


def test_samples_are_capped(tmp_path: Path) -> None:
    """L'échantillon sert à confirmer l'arborescence, pas à lister le corpus."""
    path = tmp_path / "grande.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(10):
            archive.writestr(f"OpenSubtitles/raw/en/1999/0133093/{index}.xml", "<document/>")

    with CorpusArchive(path) as archive:
        summary = archive.summarize(sample_size=2)

    assert summary.subtitle_count == 10
    assert len(summary.samples) == 2


def test_unknown_member_is_reported(sample_archive: Path) -> None:
    with (
        CorpusArchive(sample_archive) as archive,
        pytest.raises(CorpusError, match="membre absent"),
    ):
        archive.open_member("OpenSubtitles/raw/en/1999/0133093/absent.xml")


def test_truncated_archive_is_reported(tmp_path: Path) -> None:
    """Une archive incomplète doit être diagnostiquée, pas lue à moitié."""
    path = tmp_path / "tronquee.zip"
    path.write_bytes(b"PK\x03\x04 debut d'archive, puis plus rien")

    with pytest.raises(CorpusError, match="zip"):
        CorpusArchive(path)


def test_missing_archive_is_reported(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="introuvable"):
        CorpusArchive(tmp_path / "absente.zip")
