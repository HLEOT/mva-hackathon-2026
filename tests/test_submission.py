from __future__ import annotations

import csv
from pathlib import Path

import pytest

from mva_track1.common import Track1Error
from mva_track1.ranking import OUTPUT_FIELDS
from mva_track1.submission import (
    build_submission,
    reviewed_finalists,
    validate_submission_file,
)


def _write_candidates(path: Path) -> str:
    candidate_id = "BUB1B|chr15:100:A>G|chr15:200:C>T"
    row = {field: "" for field in OUTPUT_FIELDS}
    row.update(
        {
            "rank": "1", "candidate_id": candidate_id, "tier": "A", "gene": "BUB1B",
            "chrom_1": "15", "pos_1": "200", "ref_1": "C", "alt_1": "T", "gt_1": "0/1",
            "chrom_2": "chr15", "pos_2": "100", "ref_2": "A", "alt_2": "G", "gt_2": "0/1",
            "final_score": "0.9", "phase_status": "unresolved", "review_status": "PENDING",
        }
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerow(row)
    return candidate_id


def test_submission_is_canonical_and_valid(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.tsv"
    candidate_id = _write_candidates(candidates)
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
    output = tmp_path / "submission.csv"
    rows = build_submission(candidates, finalists, output, validation)
    validate_submission_file(output)
    assert rows[0]["chrom_1"] == "chr15"
    assert rows[0]["pos_1"] == "100"
    assert rows[0]["pos_2"] == "200"
    assert rows[0]["epcr"] == "0.950000"


def test_unreviewed_finalist_is_rejected(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.tsv"
    candidate_id = _write_candidates(candidates)
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        f"{candidate_id}\tYES\t1\tprimary\tREVIEW REQUIRED\n",
        encoding="utf-8",
    )
    with pytest.raises(Track1Error, match="reviewed rationale"):
        build_submission(candidates, finalists, tmp_path / "submission.csv")


@pytest.mark.parametrize(
    "reason",
    ["   ", " REVIEW REQUIRED ", "review required", "Review   Required"],
)
def test_normalized_unreviewed_rationale_is_rejected(
    tmp_path: Path, reason: str
) -> None:
    candidates = tmp_path / "candidates.tsv"
    candidate_id = _write_candidates(candidates)
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        f"{candidate_id}\tYES\t1\tprimary\t{reason}\n",
        encoding="utf-8",
    )

    with pytest.raises(Track1Error, match="reviewed rationale"):
        reviewed_finalists(finalists, candidates)


def test_final_ranks_must_be_positive_and_contiguous(tmp_path: Path) -> None:
    candidates = tmp_path / "candidates.tsv"
    candidate_id = _write_candidates(candidates)
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        f"{candidate_id}\tYES\t2\tprimary\tReviewed evidence\n",
        encoding="utf-8",
    )

    with pytest.raises(Track1Error, match="contiguous starting at 1"):
        reviewed_finalists(finalists, candidates)
