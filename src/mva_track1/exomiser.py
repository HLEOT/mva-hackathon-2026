from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .common import (
    DEFAULT_CONFIG,
    PROJECT_ROOT,
    Track1Error,
    ensure_private_dir,
    load_jsonish,
)
from .phenotype import validate_proband_config


def write_phenopacket(proband_config: Path, output: Path) -> None:
    proband = validate_proband_config(proband_config)
    sex_map = {"MALE": "MALE", "FEMALE": "FEMALE", "UNKNOWN": "UNKNOWN_SEX"}
    features = [
        {"type": {"id": term}, "excluded": False}
        for term in proband["hpo_present"]
    ] + [
        {"type": {"id": term}, "excluded": True}
        for term in proband.get("hpo_absent", [])
    ]
    packet = {
        "id": proband["proband_id"],
        "subject": {"id": proband["vcf_sample_id"], "sex": sex_map.get(proband["sex"], "UNKNOWN_SEX")},
        "phenotypicFeatures": features,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")


def run_exomiser(
    vcf: Path,
    phenopacket: Path,
    output_directory: Path,
    expected_variant_tsv: Path,
    config_path: Path | str = DEFAULT_CONFIG,
) -> None:
    cfg = load_jsonish(config_path)["annotation"]
    version = cfg["exomiser_version"]
    data_version = cfg["exomiser_data_version"]
    preset = cfg.get("exomiser_preset", "exome")
    if preset not in {"exome", "genome"}:
        raise Track1Error(f"Unsupported Exomiser preset: {preset}")
    root = PROJECT_ROOT / cfg["exomiser_dir"] / f"exomiser-cli-{version}"
    jar = root / f"exomiser-cli-{version}.jar"
    if not jar.is_file():
        matches = list(root.rglob(f"exomiser-cli-{version}.jar"))
        if not matches:
            raise Track1Error(f"Exomiser JAR not found under {root}")
        jar = matches[0]
    output_directory.mkdir(parents=True, exist_ok=True)
    java_tmp = ensure_private_dir(
        PROJECT_ROOT / "work" / "private" / "tmp" / "exomiser"
    )
    env = os.environ.copy()
    env.update(
        {
            "EXOMISER_DATA_DIRECTORY": str(root / "data"),
            "EXOMISER_HG38_DATA_VERSION": str(data_version),
            "EXOMISER_PHENOTYPE_DATA_VERSION": str(data_version),
        }
    )
    command = [
        "java",
        f"-Djava.io.tmpdir={java_tmp}",
        "-Xms4g",
        "-Xmx32g",
        "-jar",
        str(jar),
        "analyse",
        "--preset", preset, "--vcf", str(vcf), "--assembly", "GRCh38",
        "--sample", str(phenopacket), "--output-directory", str(output_directory),
        "--output-format", "TSV_VARIANT,TSV_GENE,HTML", "--output-filename", "PROBAND01",
    ]
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env, text=True, capture_output=True)
    if result.returncode:
        raise Track1Error(f"Exomiser failed:\n{result.stderr or result.stdout}")
    candidates = sorted(output_directory.glob("*variant*.tsv"))
    if not candidates:
        candidates = sorted(output_directory.glob("*.tsv"))
    if not candidates:
        raise Track1Error("Exomiser completed without a variant TSV output")
    if candidates[0].resolve() != expected_variant_tsv.resolve():
        shutil.copy2(candidates[0], expected_variant_tsv)
