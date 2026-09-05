from __future__ import annotations

import json
from pathlib import Path

import pytest

from mva_track1.common import Track1Error, sha256_file
from mva_track1.workflow_tasks import _run_manifest


def _write_environment_definitions(root: Path) -> None:
    definitions = root / "workflow" / "envs"
    definitions.mkdir(parents=True)
    for name in ("launcher", "hts", "annotation", "reads"):
        (definitions / f"{name}.yaml").write_text(
            f"dependencies:\n  - {name}\n", encoding="utf-8"
        )


def _write_gated_manifest(root: Path) -> Path:
    path = root / "data" / "gated" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "repo_id": "example/gated-dataset",
                "repo_type": "dataset",
                "revision": "0123456789abcdef",
                "files": {
                    "example.vcf.gz": {
                        "size": 12,
                        "sha256": "a" * 64,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_config(root: Path) -> None:
    path = root / "config" / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "project": {"assembly": "GRCh38"},
                "huggingface": {
                    "repo_id": "example/gated-dataset",
                    "repo_type": "dataset",
                },
            }
        ),
        encoding="utf-8",
    )


def test_run_manifest_embeds_gated_revision_and_hashes_every_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_environment_definitions(tmp_path)
    _write_config(tmp_path)
    gated_manifest = _write_gated_manifest(tmp_path)
    validation = tmp_path / "results" / "private" / "read_validation.tsv"
    validation.parent.mkdir(parents=True)
    validation.write_text("candidate_id\tevidence_status\n", encoding="utf-8")
    output = tmp_path / "results" / "private" / "final_run_manifest.json"
    monkeypatch.chdir(tmp_path.parent)

    _run_manifest(
        output,
        [
            Path("data/gated/manifest.json"),
            Path("results/private/read_validation.tsv"),
        ],
        tmp_path,
    )

    observed = json.loads(output.read_text(encoding="utf-8"))
    assert observed["gated_dataset"]["repo_id"] == "example/gated-dataset"
    assert observed["gated_dataset"]["revision"] == "0123456789abcdef"
    assert observed["assembly"] == "GRCh38"
    assert observed["inputs"]["data/gated/manifest.json"]["sha256"] == sha256_file(
        gated_manifest
    )
    assert observed["inputs"]["results/private/read_validation.tsv"][
        "sha256"
    ] == sha256_file(validation)


def test_run_manifest_requires_gated_dataset_manifest(tmp_path: Path) -> None:
    _write_environment_definitions(tmp_path)
    other = tmp_path / "input.txt"
    other.write_text("input\n", encoding="utf-8")

    with pytest.raises(Track1Error, match="omit the gated dataset manifest"):
        _run_manifest(tmp_path / "manifest.json", [other], tmp_path)


def test_run_manifest_rejects_gated_repo_config_mismatch(tmp_path: Path) -> None:
    _write_environment_definitions(tmp_path)
    _write_config(tmp_path)
    gated_manifest = _write_gated_manifest(tmp_path)
    config = json.loads((tmp_path / "config/config.yaml").read_text(encoding="utf-8"))
    config["huggingface"]["repo_id"] = "example/other-dataset"
    (tmp_path / "config/config.yaml").write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(Track1Error, match="does not match workflow configuration"):
        _run_manifest(tmp_path / "manifest.json", [gated_manifest], tmp_path)
