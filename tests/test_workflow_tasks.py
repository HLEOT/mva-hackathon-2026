from __future__ import annotations

import json
from pathlib import Path

from mva_track1 import workflow_tasks
from mva_track1.workflow_tasks import _environment_provenance


def _write_package(prefix: Path, name: str, version: str, build: str) -> None:
    metadata_dir = prefix / "conda-meta"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / f"{name}-{version}-{build}.json").write_text(
        json.dumps(
            {
                "name": name,
                "version": version,
                "build": build,
                "channel": "https://conda.example.test/bioconda",
            }
        ),
        encoding="utf-8",
    )


def test_environment_provenance_uses_matching_solved_metadata(tmp_path: Path) -> None:
    definitions = tmp_path / "workflow" / "envs"
    definitions.mkdir(parents=True)
    contents = {
        name: f"channels:\n  - conda-forge\ndependencies:\n  - {name}\n"
        for name in ("launcher", "hts", "annotation", "reads")
    }
    for name, content in contents.items():
        (definitions / f"{name}.yaml").write_text(content, encoding="utf-8")

    prefix_root = tmp_path / ".conda" / "rules"
    prefix_root.mkdir(parents=True)
    scheduler_prefix = tmp_path / ".conda" / "launcher"
    _write_package(scheduler_prefix, "snakemake-minimal", "9.6.2", "pyhdfd78af_0")
    (scheduler_prefix / "conda-meta" / "history").touch()

    launcher_definition = prefix_root / "launcher_hash_.yaml"
    launcher_definition.write_text(contents["launcher"], encoding="utf-8")
    launcher_prefix = launcher_definition.with_suffix("")
    _write_package(launcher_prefix, "python", "3.12.14", "hd63d673_0_cpython")
    Path(f"{launcher_prefix}.env_setup_done").touch()

    annotation_definition = prefix_root / "annotation_hash_.yaml"
    annotation_definition.write_text(contents["annotation"], encoding="utf-8")
    annotation_prefix = annotation_definition.with_suffix("")
    _write_package(annotation_prefix, "ensembl-vep", "116.1", "pl5321hdfd78af_0")
    _write_package(annotation_prefix, "openjdk", "21.0.8", "h8c5f2b5_0")
    Path(f"{annotation_prefix}.env_setup_done").touch()

    reads_definition = prefix_root / "reads_hash_.yaml"
    reads_definition.write_text(contents["reads"], encoding="utf-8")
    _write_package(reads_definition.with_suffix(""), "bwa-mem2", "2.2.1", "he70b90d_5")

    environments, tools = _environment_provenance(tmp_path)

    assert environments["launcher"]["status"] == "ready"
    assert environments["scheduler"]["status"] == "ready"
    assert environments["hts"]["status"] == "environment_not_built"
    assert environments["reads"]["status"] == "environment_incomplete"
    assert environments["annotation"]["packages"]["ensembl-vep"]["version"] == "116.1"
    assert tools["scheduler.snakemake"] == {
        "status": "ready",
        "environment": "scheduler",
        "package": "snakemake-minimal",
        "version": "9.6.2",
        "build": "pyhdfd78af_0",
        "channel": "https://conda.example.test/bioconda",
    }
    assert tools["hts.bcftools"]["status"] == "environment_not_built"
    assert tools["annotation.vep"]["version"] == "116.1"
    assert tools["annotation.java"]["version"] == "21.0.8"
    assert tools["reads.bwa_mem2"]["status"] == "environment_incomplete"


def test_verify_vep_cache_task_validates_manifest_before_marker(
    tmp_path: Path, monkeypatch
) -> None:
    marker = tmp_path / "vep" / ".v116_merged_complete"
    manifest = tmp_path / "vep" / "install_manifest.json"
    events = []

    def fake_create_manifest() -> Path:
        events.append("create_manifest")
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}\n", encoding="utf-8")
        return manifest

    def fake_verify(*, require_marker: bool, require_manifest: bool = True) -> None:
        events.append(("verify", require_marker, require_manifest))

    monkeypatch.setattr(
        workflow_tasks, "create_vep_install_manifest", fake_create_manifest
    )
    monkeypatch.setattr(workflow_tasks, "verify_vep_cache", fake_verify)

    assert workflow_tasks.main(
        [
            "verify-vep-cache",
            "--output",
            str(marker),
            "--manifest",
            str(manifest),
        ]
    ) == 0

    assert events == ["create_manifest", ("verify", False, True)]
    assert marker.read_text(encoding="utf-8") == "complete\n"
