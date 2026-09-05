from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from mva_track1.artifacts import (
    CONFIG_INPUT,
    EMPTY_SHA256,
    FINAL_MANIFEST_REQUIRED_TOOLS,
    GATED_MANIFEST_INPUT,
    LAUNCHER_INPUT,
    PROJECT_METADATA_INPUT,
    READ_VALIDATION_FIELDS,
    validate_final_run_manifest,
    validate_read_validation,
)
from mva_track1.common import Track1Error, sha256_file


PROBAND_ID = "SYNTHETIC01"
CRAM_INPUT = f"work/private/alignment/{PROBAND_ID}.cram"
VEP_MANIFEST_INPUT = "resources/custom-vep/install_manifest.json"
EXOMISER_MANIFEST_INPUT = "resources/custom-exomiser/install_manifest.json"
SOURCE_INPUT = "src/mva_track1/synthetic.py"


def _review_files(
    root: Path, candidate_ids: tuple[str, ...] = ("candidate-1",)
) -> tuple[Path, Path]:
    candidates = root / "candidates.tsv"
    candidates.write_text(
        "candidate_id\n" + "".join(f"{candidate_id}\n" for candidate_id in candidate_ids),
        encoding="utf-8",
    )
    finalists = root / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        + "".join(
            f"{candidate_id}\tYES\t{rank}\tprimary\tReviewed evidence\n"
            for rank, candidate_id in enumerate(candidate_ids, 1)
        ),
        encoding="utf-8",
    )
    return candidates, finalists


def _validation_row(candidate_id: str = "candidate-1") -> dict[str, str]:
    row = {field: "0" for field in READ_VALIDATION_FIELDS}
    row.update(
        {
            "candidate_id": candidate_id,
            "pair_support": "supported",
            "phase_status": "not_applicable_single_variant",
            "phase_method": "not_applicable",
            "whatshap_phase_set": "",
            "v1_support": "supported",
            "v2_support": "",
        }
    )
    return row


def _write_validation(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=READ_VALIDATION_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def _write_file(root: Path, relative: str, content: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _record(path: Path) -> dict[str, int | str]:
    return {"size": path.stat().st_size, "sha256": sha256_file(path)}


def _write_manifest(root: Path, validation: Path) -> Path:
    gated_dataset = {
        "repo_id": "example/gated-dataset",
        "repo_type": "dataset",
        "revision": "0123456789abcdef",
        "files": {"example.vcf.gz": {"size": 12, "sha256": "a" * 64}},
    }
    config = {
        "project": {"assembly": "GRCh38", "proband_id": PROBAND_ID},
        "huggingface": {
            "repo_id": gated_dataset["repo_id"],
            "repo_type": gated_dataset["repo_type"],
        },
        "annotation": {
            "vep_cache_dir": "resources/custom-vep",
            "exomiser_dir": "resources/custom-exomiser",
        },
    }
    files = {
        validation.relative_to(root).as_posix(): validation,
        CONFIG_INPUT: _write_file(root, CONFIG_INPUT, json.dumps(config).encode()),
        GATED_MANIFEST_INPUT: _write_file(
            root, GATED_MANIFEST_INPUT, json.dumps(gated_dataset).encode()
        ),
        VEP_MANIFEST_INPUT: _write_file(root, VEP_MANIFEST_INPUT, b'{"version":"116"}\n'),
        EXOMISER_MANIFEST_INPUT: _write_file(
            root, EXOMISER_MANIFEST_INPUT, b'{"version":"15.1.0"}\n'
        ),
        CRAM_INPUT: _write_file(root, CRAM_INPUT, b"synthetic-cram"),
        LAUNCHER_INPUT: _write_file(root, LAUNCHER_INPUT, b"#!/bin/sh\n"),
        PROJECT_METADATA_INPUT: _write_file(
            root, PROJECT_METADATA_INPUT, b'[project]\nname="synthetic"\n'
        ),
        SOURCE_INPUT: _write_file(root, SOURCE_INPUT, b"VALUE = 1\n"),
        "workflow/Snakefile": _write_file(root, "workflow/Snakefile", b"rule all:\n    input: []\n"),
        "resources/public/marker": _write_file(root, "resources/public/marker", b""),
    }
    path = root / "results" / "private" / "final_run_manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "privacy_mode": "local-only",
                "assembly": "GRCh38",
                "gated_dataset": gated_dataset,
                "tools": {
                    name: {"status": "ready"}
                    for name in FINAL_MANIFEST_REQUIRED_TOOLS
                },
                "inputs": {name: _record(file_path) for name, file_path in files.items()},
            }
        ),
        encoding="utf-8",
    )
    return path


def test_read_validation_requires_exact_schema_and_one_row_per_finalist(tmp_path: Path) -> None:
    candidates, finalists = _review_files(tmp_path, ("candidate-1", "candidate-2"))
    validation = tmp_path / "validation.tsv"
    _write_validation(
        validation,
        [_validation_row("candidate-1"), _validation_row("candidate-2")],
    )
    assert len(validate_read_validation(validation, finalists, candidates)) == 2

    _write_validation(validation, [_validation_row("candidate-1")])
    with pytest.raises(Track1Error, match="exactly one row"):
        validate_read_validation(validation, finalists, candidates)

    validation.write_text("candidate_id\tpair_support\ncandidate-1\tsupported\n", encoding="utf-8")
    with pytest.raises(Track1Error, match="schema"):
        validate_read_validation(validation, finalists, candidates)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pair_support", "maybe"),
        ("phase_status", "unreviewed"),
        ("phase_method", "unknown"),
        ("v1_support", "likely"),
        ("v2_support", "likely"),
    ],
)
def test_read_validation_rejects_unknown_evidence_values(
    tmp_path: Path, field: str, value: str
) -> None:
    candidates, finalists = _review_files(tmp_path)
    validation = tmp_path / "validation.tsv"
    row = _validation_row()
    row[field] = value
    _write_validation(validation, [row])
    with pytest.raises(Track1Error, match=field):
        validate_read_validation(validation, finalists, candidates)


def test_final_manifest_requires_ready_tools_and_current_inputs(tmp_path: Path) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    validate_final_run_manifest(manifest, validation, tmp_path)

    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["tools"]["reads.whatshap"]["status"] = "environment_incomplete"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(Track1Error, match="reads.whatshap"):
        validate_final_run_manifest(manifest, validation, tmp_path)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("privacy_mode", "public", "privacy_mode"),
        ("assembly", "GRCh37", "assembly"),
        ("gated_dataset", {}, "gated_dataset"),
    ],
)
def test_final_manifest_requires_final_provenance_structure(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    observed = json.loads(manifest.read_text(encoding="utf-8"))
    observed[field] = value
    manifest.write_text(json.dumps(observed), encoding="utf-8")
    with pytest.raises(Track1Error, match=message):
        validate_final_run_manifest(manifest, validation, tmp_path)


@pytest.mark.parametrize(
    "input_name",
    [
        CONFIG_INPUT,
        GATED_MANIFEST_INPUT,
        CRAM_INPUT,
        VEP_MANIFEST_INPUT,
        EXOMISER_MANIFEST_INPUT,
        LAUNCHER_INPUT,
        PROJECT_METADATA_INPUT,
        SOURCE_INPUT,
    ],
)
def test_final_manifest_requires_named_provenance_inputs(
    tmp_path: Path, input_name: str
) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    observed = json.loads(manifest.read_text(encoding="utf-8"))
    del observed["inputs"][input_name]
    manifest.write_text(json.dumps(observed), encoding="utf-8")
    with pytest.raises(Track1Error, match="required input"):
        validate_final_run_manifest(manifest, validation, tmp_path)


@pytest.mark.parametrize(
    "input_name",
    [
        GATED_MANIFEST_INPUT,
        VEP_MANIFEST_INPUT,
        EXOMISER_MANIFEST_INPUT,
        "workflow/Snakefile",
        SOURCE_INPUT,
    ],
)
def test_final_manifest_verifies_every_current_small_input(
    tmp_path: Path, input_name: str
) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    path = tmp_path / input_name
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(Track1Error, match="stale input hash"):
        validate_final_run_manifest(manifest, validation, tmp_path)


def test_final_manifest_skips_cram_hash_for_status_but_checks_it_for_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    cram = tmp_path / CRAM_INPUT
    original_sha256_file = sha256_file

    def guarded_sha256_file(path: Path) -> str:
        assert path.resolve() != cram.resolve()
        return original_sha256_file(path)

    monkeypatch.setattr("mva_track1.artifacts.sha256_file", guarded_sha256_file)
    validate_final_run_manifest(manifest, validation, tmp_path, verify_large_hashes=False)
    monkeypatch.undo()

    original = cram.read_bytes()
    cram.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    validate_final_run_manifest(manifest, validation, tmp_path, verify_large_hashes=False)
    with pytest.raises(Track1Error, match="stale input hash"):
        validate_final_run_manifest(manifest, validation, tmp_path, verify_large_hashes=True)


def test_final_manifest_rejects_cram_size_drift(tmp_path: Path) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    with (tmp_path / CRAM_INPUT).open("ab") as handle:
        handle.write(b"x")
    with pytest.raises(Track1Error, match="stale input size"):
        validate_final_run_manifest(manifest, validation, tmp_path)


def test_final_manifest_rejects_input_symlink_escape(tmp_path: Path) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    marker = tmp_path / "resources/public/marker"
    marker.unlink()
    outside = tmp_path.parent / f"{tmp_path.name}-outside-marker"
    outside.write_bytes(b"")
    marker.symlink_to(outside)
    with pytest.raises(Track1Error, match="outside the project"):
        validate_final_run_manifest(manifest, validation, tmp_path)


def test_final_manifest_rejects_missing_or_stale_validation_record(tmp_path: Path) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    validation_key = validation.relative_to(tmp_path).as_posix()
    del value["inputs"][validation_key]
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(Track1Error, match="required input"):
        validate_final_run_manifest(manifest, validation, tmp_path)

    manifest = _write_manifest(tmp_path, validation)
    validation.write_text("changed\n", encoding="utf-8")
    with pytest.raises(Track1Error, match="stale input"):
        validate_final_run_manifest(manifest, validation, tmp_path)


def test_final_manifest_rejects_malformed_hash_metadata(tmp_path: Path) -> None:
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    _write_validation(validation, [_validation_row()])
    manifest = _write_manifest(tmp_path, validation)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["inputs"]["resources/public/marker"]["sha256"] = "not-a-sha256"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(Track1Error, match="invalid size or SHA-256"):
        validate_final_run_manifest(manifest, validation, tmp_path)
