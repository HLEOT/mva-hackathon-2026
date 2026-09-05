from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from mva_track1.common import Track1Error
from mva_track1.phenotype import (
    extract_hpo,
    suggest_hpo_status,
    validate_proband_config,
)


def test_extracts_unique_hpo_ids_from_docx(tmp_path: Path) -> None:
    docx = tmp_path / "phenotype.docx"
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body><w:p><w:r><w:t>Observed HP:0000252 and HP:0000252; absent HP:0001250.</w:t></w:r></w:p></w:body>
    </w:document>"""
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("word/document.xml", xml)
    output = tmp_path / "hpo.tsv"
    found = extract_hpo(docx, output)
    assert {row["hpo_id"] for row in found} == {"HP:0000252", "HP:0001250"}
    assert all(row["status"] == "REVIEW" for row in found)


def test_placeholder_proband_config_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "proband.json"
    path.write_text(
        '{"proband_id":"PROBAND01","vcf_sample_id":"REPLACE_WITH_VCF_SAMPLE_ID",'
        '"hpo_present":["HP:0000000"],"hpo_absent":[],"reviewed_by":"REPLACE",'
        '"reviewed_at":"YYYY-MM-DD"}',
        encoding="utf-8",
    )
    with pytest.raises(Track1Error):
        validate_proband_config(path)


@pytest.mark.parametrize("reviewer", ["   ", " replace_with_reviewer "])
def test_normalized_reviewer_placeholder_is_rejected(
    tmp_path: Path, reviewer: str
) -> None:
    path = tmp_path / "proband.json"
    path.write_text(
        '{"proband_id":"PROBAND01","vcf_sample_id":"synthetic-sample",'
        '"hpo_present":["HP:0000001"],"hpo_absent":[],'
        f'"reviewed_by":"{reviewer}","reviewed_at":"2026-08-25"}}',
        encoding="utf-8",
    )

    with pytest.raises(Track1Error, match="reviewed_by"):
        validate_proband_config(path)


def test_local_negation_suggestions_remain_explicitly_nonfinal() -> None:
    assert suggest_hpo_status(
        "HP:0001250", "Observed seizures HP:0001250 during infancy."
    ) == ("LIKELY_PRESENT", "no_local_negation_cue")
    assert suggest_hpo_status(
        "HP:0001250", "There were no seizures HP:0001250 during infancy."
    ) == ("LIKELY_ABSENT", "local_negation_cue")
