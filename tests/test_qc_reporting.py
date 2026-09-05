"""Invented QC metadata only; fixtures contain no read sequences."""
import zipfile

import pytest

from mva_runner.qc import MODULES, read_fastqc_summary, report_section
from mva_runner.render import inspect_pdf, markdown_to_pdf
from mva_runner.supervisor import stages
from mva_track1.common import Track1Error


def fixture(root, flags=None, omit=None, version="0.12.1"):
    directory = root / "fastqc"
    directory.mkdir(parents=True)
    names = ["synthetic_1.fastq.gz", "synthetic_2.fastq.gz"]
    for name in names:
        prefix = name.removesuffix(".fastq.gz") + "_fastqc"
        rows = [f"{(flags or {}).get(module, 'PASS')}\t{module}\t{name}" for module in sorted(MODULES) if module != omit]
        with zipfile.ZipFile(directory / (prefix + ".zip"), "w") as source:
            source.writestr(prefix + "/summary.txt", "\n".join(rows) + "\n")
            source.writestr(prefix + "/fastqc_data.txt", "##FastQC\t" + version + "\n")
        (directory / (prefix + ".html")).write_text("<html>synthetic</html>")
    (root / "multiqc_report.html").write_text("<html>synthetic combined report</html>")
    return names


def test_flags_are_retained_separately_from_artifact_integrity(tmp_path):
    names = fixture(tmp_path, {"Per base sequence content": "FAIL", "Per sequence GC content": "WARN"})
    result = read_fastqc_summary(tmp_path, names)
    assert result["artifact_integrity_verified"] is True
    assert result["all_modules_passed"] is False
    rows = {row["module"]: row for row in result["modules"]}
    assert rows["Per base sequence content"]["FAIL"] == 2
    assert rows["Per sequence GC content"]["WARN"] == 2
    assert len(result["archives"]) == 2
    text = report_section(result)
    assert "FAIL in 2 reports" in text and "WARN in 2 reports" in text
    assert "causes of composition or GC flags are not established" in text
    assert "synthetic_1" not in text


def test_all_pass_is_screening_not_scientific_proof(tmp_path):
    result = read_fastqc_summary(tmp_path, fixture(tmp_path))
    assert result["all_modules_passed"] is True
    assert "not proof of variant validity" in report_section(result)


def test_report_inventory_must_match_input_identity_not_just_count(tmp_path):
    fixture(tmp_path)
    with pytest.raises(Track1Error, match="inventory"):
        read_fastqc_summary(tmp_path, ["different_1.fastq.gz", "different_2.fastq.gz"])


@pytest.mark.parametrize("kwargs, message", [
    ({"omit": "Adapter Content"}, "omits"),
    ({"flags": {"Adapter Content": "UNKNOWN"}}, "invalid or duplicate"),
    ({"version": "0.0.0"}, "version differs"),
])
def test_incomplete_or_unexpected_summaries_fail_closed(tmp_path, kwargs, message):
    names = fixture(tmp_path, **kwargs)
    with pytest.raises(Track1Error, match=message):
        read_fastqc_summary(tmp_path, names)


def test_incomplete_multiqc_document_is_rejected(tmp_path):
    names = fixture(tmp_path)
    (tmp_path / "multiqc_report.html").write_text("<html>unfinished")
    with pytest.raises(Track1Error, match="incomplete"):
        read_fastqc_summary(tmp_path, names)


def test_archive_crc_failure_is_not_treated_as_a_quality_flag(tmp_path, monkeypatch):
    names = fixture(tmp_path)
    monkeypatch.setattr(zipfile.ZipFile, "testzip", lambda self: "synthetic-corrupt-member")
    with pytest.raises(Track1Error, match="CRC check"):
        read_fastqc_summary(tmp_path, names)


def test_symlinked_report_is_rejected(tmp_path):
    names = fixture(tmp_path)
    report = next((tmp_path / "fastqc").glob("*.html"))
    report.unlink()  # Only this test's invented fixture is replaced.
    report.symlink_to(tmp_path / "multiqc_report.html")
    with pytest.raises(Track1Error, match="regular files"):
        read_fastqc_summary(tmp_path, names)


def test_qc_caveats_render_without_clipping(tmp_path):
    result = read_fastqc_summary(tmp_path, fixture(tmp_path, {"Per base sequence content": "FAIL"}))
    source, pdf = tmp_path / "synthetic.md", tmp_path / "synthetic.pdf"
    source.write_text(report_section(result))
    markdown_to_pdf(source, pdf)
    inspected = inspect_pdf(pdf)
    assert inspected["clipped_words"] == 0


def test_qc_reporting_changes_invalidate_packaging_not_read_measurements():
    stage = {item.name: item for item in stages()}
    assert "src/mva_runner/qc.py" in stage["package"].inputs
    assert "src/mva_runner/qc.py" not in stage["validate_reads"].inputs
    assert "src/mva_runner/qc.py" not in stage["prioritise"].inputs
