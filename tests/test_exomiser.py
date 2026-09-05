from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from mva_track1 import exomiser


def test_run_exomiser_constructs_grch38_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(exomiser, "PROJECT_ROOT", tmp_path)
    version = "15.1.0"
    root = tmp_path / "resources" / "public" / "exomiser"
    cli_root = root / f"exomiser-cli-{version}"
    cli_root.mkdir(parents=True)
    (cli_root / f"exomiser-cli-{version}.jar").write_bytes(b"synthetic jar")
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "annotation": {
                    "exomiser_version": version,
                    "exomiser_data_version": "2602",
                    "exomiser_preset": "exome",
                    "exomiser_dir": "resources/public/exomiser",
                }
            }
        ),
        encoding="utf-8",
    )
    vcf = tmp_path / "synthetic.vcf"
    vcf.write_text("##fileformat=VCFv4.2\n", encoding="utf-8")
    phenopacket = tmp_path / "synthetic.json"
    phenopacket.write_text("{}\n", encoding="utf-8")
    output_directory = tmp_path / "output"
    expected_variant_tsv = output_directory / "PROBAND01.variants.tsv"
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        expected_variant_tsv.write_text("synthetic\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(exomiser.subprocess, "run", fake_run)
    exomiser.run_exomiser(
        vcf,
        phenopacket,
        output_directory,
        expected_variant_tsv,
        config,
    )

    command = captured["command"]
    java_tmp = tmp_path / "work" / "private" / "tmp" / "exomiser"
    assert command[1] == f"-Djava.io.tmpdir={java_tmp}"
    assert java_tmp.stat().st_mode & 0o777 == 0o700
    assembly_index = command.index("--assembly")
    assert command[assembly_index + 1] == "GRCh38"
    assert "hg38" not in command
    assert captured["kwargs"]["env"]["EXOMISER_HG38_DATA_VERSION"] == "2602"
