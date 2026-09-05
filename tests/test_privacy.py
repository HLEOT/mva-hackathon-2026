from __future__ import annotations

from pathlib import Path

import pytest

from mva_track1 import privacy
from mva_track1.common import Track1Error


def test_purge_includes_generated_submissions_but_preserves_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    placeholder = submissions / ".gitkeep"
    placeholder.touch()
    generated = [
        submissions / "synthetic_track1-ranked.csv",
        submissions / "synthetic_track1_report.md",
        submissions / "synthetic_track1_report.pdf",
        submissions / "synthetic_track1_bundle.zip",
        submissions / "submission_log.tsv",
    ]
    for path in generated:
        path.write_text("synthetic\n", encoding="utf-8")
    unrelated = submissions / "keep.txt"
    unrelated.write_text("keep\n", encoding="utf-8")
    monkeypatch.setattr(privacy, "PROJECT_ROOT", tmp_path)

    preview = privacy.purge_preview()

    assert set(preview) == {path.resolve() for path in generated}
    receipt = privacy.purge_confirmed("DELETE MVA GATED DATA")
    assert receipt.is_file()
    assert placeholder.is_file()
    assert unrelated.is_file()
    assert all(not path.exists() for path in generated)


def test_purge_rejects_generated_submission_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    submissions = tmp_path / "submissions"
    submissions.mkdir()
    outside = tmp_path.parent / "outside-track1.csv"
    link = submissions / "synthetic_track1-ranked.csv"
    link.symlink_to(outside)
    monkeypatch.setattr(privacy, "PROJECT_ROOT", tmp_path)

    with pytest.raises(Track1Error, match="symbolic link"):
        privacy.purge_preview()


@pytest.mark.parametrize(
    "filename",
    [
        "patient.vcf",
        "patient.vcf.gz",
        "patient.bcf",
        "patient.bam",
        "patient.cram",
        "patient.crai",
        "patient.tbi",
        "reads.fastq",
        "reads.fastq.gz",
        "reads.fq",
        "reads.fq.gz",
        "reads.FASTQ.GZ",
    ],
)
def test_audit_rejects_tracked_patient_data_extensions_globally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    tracked = tmp_path / "otherwise-public-looking" / filename
    tracked.parent.mkdir(parents=True)
    tracked.write_bytes(b"synthetic")
    monkeypatch.setattr(privacy, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(privacy, "tracked_files", lambda: [tracked])

    with pytest.raises(Track1Error, match="patient-data extension"):
        privacy.audit_tracked_files()


def test_audit_allows_explicit_public_reference_and_vep_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference = tmp_path / "resources" / "public" / "reference" / "public.vcf.gz"
    vep_index = tmp_path / "resources" / "public" / "vep" / "all_vars.gz.csi"
    for path in (reference, vep_index):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic public resource")
    monkeypatch.setattr(privacy, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(privacy, "tracked_files", lambda: [reference, vep_index])

    assert privacy.audit_tracked_files() == [
        "resources/public/reference/public.vcf.gz",
        "resources/public/vep/all_vars.gz.csi",
    ]
