from __future__ import annotations

from pathlib import Path

from mva_track1.report import generate_markdown, markdown_to_pdf


def test_methods_report_and_pdf_are_generated(tmp_path: Path) -> None:
    candidate_id = "BUB1B|chr15:100:A>G|chr15:200:C>T"
    candidates = tmp_path / "candidates.tsv"
    candidates.write_text(
        "candidate_id\tgene\tchrom_1\tpos_1\tref_1\talt_1\tchrom_2\tpos_2\tref_2\talt_2\ttier\tfinal_score\n"
        f"{candidate_id}\tBUB1B\tchr15\t100\tA\tG\tchr15\t200\tC\tT\tA\t0.9\n",
        encoding="utf-8",
    )
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        f"{candidate_id}\tYES\t1\tprimary\tStrong biallelic evidence\n",
        encoding="utf-8",
    )
    validation = tmp_path / "validation.tsv"
    validation.write_text(
        "candidate_id\tpair_support\n" f"{candidate_id}\tsupported\n",
        encoding="utf-8",
    )
    markdown = tmp_path / "report.md"
    pdf = tmp_path / "report.pdf"
    generate_markdown(
        candidates, finalists, validation, tmp_path / "manifest.json", markdown,
        "https://github.com/example/mva-track1",
    )
    markdown_to_pdf(markdown, pdf)
    assert "not a clinical diagnosis" in markdown.read_text(encoding="utf-8")
    assert pdf.read_bytes().startswith(b"%PDF")
