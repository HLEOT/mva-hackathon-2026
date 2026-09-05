from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .common import PROJECT_ROOT, Track1Error, load_jsonish, sha256_file
from .submission import reviewed_finalists


READ_VALIDATION_FIELDS = [
    "candidate_id", "pair_support", "phase_status",
    "phase_method", "whatshap_phase_set",
    "phase_informative_fragments", "phase_cis_fragments", "phase_trans_fragments",
    "v1_depth", "v1_ref_reads", "v1_alt_reads", "v1_vaf",
    "v1_alt_forward", "v1_alt_reverse", "v1_mean_mq", "v1_mean_bq", "v1_support",
    "v2_depth", "v2_ref_reads", "v2_alt_reads", "v2_vaf",
    "v2_alt_forward", "v2_alt_reverse", "v2_mean_mq", "v2_mean_bq", "v2_support",
]

PAIR_SUPPORT_VALUES = frozenset({"supported", "unsupported", "ambiguous"})
ALLELE_SUPPORT_VALUES = PAIR_SUPPORT_VALUES
PHASE_STATUS_VALUES = frozenset(
    {
        "not_applicable_single_variant",
        "not_applicable_different_chromosomes",
        "read_linkage_supports_trans",
        "read_linkage_supports_cis",
        "conflicting_read_linkage",
        "unresolved_insufficient_linkage",
        "whatshap_supports_trans",
        "whatshap_supports_cis",
        "conflicting_phase_methods",
    }
)
PHASE_METHOD_VALUES = frozenset(
    {
        "not_applicable",
        "direct_fragment_linkage",
        "whatshap",
        "whatshap_and_direct_fragment_linkage",
    }
)

FINAL_MANIFEST_REQUIRED_TOOLS = frozenset(
    {
        "scheduler.snakemake",
        "launcher_rule.python",
        "hts.bcftools",
        "hts.samtools",
        "annotation.bcftools",
        "annotation.vep",
        "annotation.java",
        "reads.bwa_mem2",
        "reads.samtools",
        "reads.bcftools",
        "reads.fastqc",
        "reads.multiqc",
        "reads.mosdepth",
        "reads.whatshap",
        "reads.seqkit",
        "reads.gzip",
        "reads.pysam",
    }
)
EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
CONFIG_INPUT = "config/config.yaml"
GATED_MANIFEST_INPUT = "data/gated/manifest.json"
LAUNCHER_INPUT = "mva-track1"
PROJECT_METADATA_INPUT = "pyproject.toml"


def _require_allowed(row: dict[str, str], field: str, allowed: frozenset[str]) -> None:
    value = row.get(field, "")
    if value not in allowed:
        raise Track1Error(
            f"Raw-read validation has invalid {field} for {row.get('candidate_id', '<missing>')}"
        )


def validate_read_validation(
    path: Path,
    finalists_path: Path,
    candidates_path: Path,
) -> list[dict[str, str]]:
    """Validate the private evidence table without interpreting patient measurements."""
    selected = reviewed_finalists(finalists_path, candidates_path)
    expected_ids = {row["candidate_id"] for row in selected}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if reader.fieldnames != READ_VALIDATION_FIELDS:
                raise Track1Error(
                    "Raw-read validation schema does not match the pipeline output"
                )
            rows = list(reader)
    except OSError as exc:
        raise Track1Error(f"Could not read raw-read validation artifact: {exc}") from exc

    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise Track1Error("Raw-read validation row does not match the pipeline schema")
    candidate_ids = [row.get("candidate_id", "") for row in rows]
    if not all(candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
        raise Track1Error(
            "Raw-read validation candidate_id values must be present and unique"
        )
    if len(rows) != len(expected_ids) or set(candidate_ids) != expected_ids:
        raise Track1Error(
            "Raw-read validation must contain exactly one row per reviewed finalist"
        )

    for row in rows:
        _require_allowed(row, "pair_support", PAIR_SUPPORT_VALUES)
        _require_allowed(row, "phase_status", PHASE_STATUS_VALUES)
        _require_allowed(row, "phase_method", PHASE_METHOD_VALUES)
        _require_allowed(row, "v1_support", ALLELE_SUPPORT_VALUES)
        v2_support = row.get("v2_support", "")
        if v2_support and v2_support not in ALLELE_SUPPORT_VALUES:
            raise Track1Error(
                f"Raw-read validation has invalid v2_support for {row['candidate_id']}"
            )
    return rows


def _load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Track1Error(f"Could not parse final run manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise Track1Error("Final run manifest must contain a JSON object")
    return value


def _verify_current_input(
    inputs: dict[str, Any],
    input_name: str,
    project_root: Path,
    *,
    verify_hash: bool,
) -> Path:
    record = inputs.get(input_name)
    if not isinstance(record, dict):
        raise Track1Error(f"Final run manifest does not record required input: {input_name}")
    try:
        path = (project_root / input_name).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Track1Error(f"Required final provenance input is unavailable: {input_name}") from exc
    try:
        path.relative_to(project_root)
    except ValueError as exc:
        raise Track1Error(
            f"Final provenance input resolves outside the project: {input_name}"
        ) from exc
    if not path.is_file():
        raise Track1Error(f"Final provenance input is not a regular file: {input_name}")
    size = path.stat().st_size
    if record.get("size") != size:
        raise Track1Error(f"Final run manifest records stale input size: {input_name}")
    if verify_hash:
        try:
            digest = sha256_file(path)
        except OSError as exc:
            raise Track1Error(f"Could not verify final provenance input: {input_name}") from exc
        if record.get("sha256") != digest:
            raise Track1Error(f"Final run manifest records stale input hash: {input_name}")
    return path


def _safe_configured_directory(value: Any, label: str) -> Path:
    path = Path(str(value))
    if path == Path(".") or path.is_absolute() or ".." in path.parts:
        raise Track1Error(f"Configured {label} must be a project-relative directory")
    return path


def _current_provenance_identity(project_root: Path) -> dict[str, str]:
    try:
        config = load_jsonish(project_root / CONFIG_INPUT)
        project = config["project"]
        huggingface = config["huggingface"]
        annotation = config["annotation"]
        assembly = str(project["assembly"])
        proband_id = str(project["proband_id"])
        repo_id = str(huggingface["repo_id"])
        repo_type = str(huggingface["repo_type"])
        vep_dir = _safe_configured_directory(
            annotation["vep_cache_dir"], "VEP cache directory"
        )
        exomiser_dir = _safe_configured_directory(
            annotation["exomiser_dir"], "Exomiser directory"
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise Track1Error("Current workflow configuration is unreadable or incomplete") from exc
    if not assembly or not repo_id or not repo_type:
        raise Track1Error("Current workflow provenance identity is incomplete")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", proband_id) is None:
        raise Track1Error("Configured proband_id is unsafe for provenance paths")
    return {
        "assembly": assembly,
        "repo_id": repo_id,
        "repo_type": repo_type,
        "cram": (Path("work/private/alignment") / f"{proband_id}.cram").as_posix(),
        "vep_manifest": (vep_dir / "install_manifest.json").as_posix(),
        "exomiser_manifest": (exomiser_dir / "install_manifest.json").as_posix(),
    }


def _source_provenance_inputs(project_root: Path) -> tuple[str, ...]:
    sources = tuple(
        path.relative_to(project_root).as_posix()
        for path in sorted((project_root / "src" / "mva_track1").glob("*.py"))
    )
    if not sources:
        raise Track1Error("No Python source files are available for provenance")
    return sources


def validate_final_run_manifest(
    path: Path,
    validation_path: Path,
    project_root: Path = PROJECT_ROOT,
    *,
    verify_large_hashes: bool = False,
) -> dict[str, Any]:
    """Require a complete, current post-validation provenance manifest."""
    project_root = project_root.resolve()
    identity = _current_provenance_identity(project_root)
    manifest = _load_manifest(path)
    if manifest.get("privacy_mode") != "local-only":
        raise Track1Error("Final run manifest privacy_mode must be local-only")
    if manifest.get("assembly") != identity["assembly"]:
        raise Track1Error("Final run manifest assembly does not match current config")
    gated_dataset = manifest.get("gated_dataset")
    if not isinstance(gated_dataset, dict):
        raise Track1Error("Final run manifest lacks gated dataset provenance")
    for field in ("repo_id", "repo_type", "revision"):
        if not isinstance(gated_dataset.get(field), str) or not gated_dataset[field]:
            raise Track1Error(f"Final run manifest gated_dataset lacks {field}")
    if not isinstance(gated_dataset.get("files"), dict) or not gated_dataset["files"]:
        raise Track1Error("Final run manifest gated_dataset lacks file records")
    if (
        gated_dataset.get("repo_id") != identity["repo_id"]
        or gated_dataset.get("repo_type") != identity["repo_type"]
    ):
        raise Track1Error("Final run manifest gated dataset does not match current config")

    tools = manifest.get("tools")
    if not isinstance(tools, dict):
        raise Track1Error("Final run manifest lacks tool provenance")
    for tool in sorted(FINAL_MANIFEST_REQUIRED_TOOLS):
        record = tools.get(tool)
        if not isinstance(record, dict) or record.get("status") != "ready":
            raise Track1Error(f"Final run manifest tool is not ready: {tool}")

    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict) or not inputs:
        raise Track1Error("Final run manifest lacks input provenance")
    for input_name, record in inputs.items():
        input_path = Path(input_name) if isinstance(input_name, str) else Path(".")
        if (
            not isinstance(input_name, str)
            or not input_name
            or input_path == Path(".")
            or input_path.is_absolute()
            or ".." in input_path.parts
            or not isinstance(record, dict)
        ):
            raise Track1Error("Final run manifest contains an invalid input record")
        size = record.get("size")
        digest = record.get("sha256")
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or size < 0
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            or (size == 0 and digest != EMPTY_SHA256)
            or (size > 0 and digest == EMPTY_SHA256)
        ):
            raise Track1Error(
                f"Final run manifest contains invalid size or SHA-256 metadata: {input_name}"
            )

    try:
        validation_key = validation_path.resolve().relative_to(project_root).as_posix()
    except ValueError as exc:
        raise Track1Error("Raw-read validation path is outside the project root") from exc
    required_inputs = {
        validation_key,
        CONFIG_INPUT,
        GATED_MANIFEST_INPUT,
        identity["cram"],
        identity["vep_manifest"],
        identity["exomiser_manifest"],
        LAUNCHER_INPUT,
        PROJECT_METADATA_INPUT,
        *_source_provenance_inputs(project_root),
    }
    missing_inputs = sorted(required_inputs - set(inputs))
    if missing_inputs:
        raise Track1Error(
            f"Final run manifest does not record required input: {missing_inputs[0]}"
        )

    current_inputs = {
        input_name: _verify_current_input(
            inputs,
            input_name,
            project_root,
            verify_hash=(input_name != identity["cram"] or verify_large_hashes),
        )
        for input_name in inputs
    }
    if current_inputs[validation_key].stat().st_size <= 0:
        raise Track1Error("Raw-read validation artifact is empty")
    if current_inputs[identity["cram"]].stat().st_size <= 0:
        raise Track1Error("Final provenance CRAM is empty")
    for manifest_input in (
        GATED_MANIFEST_INPUT,
        identity["vep_manifest"],
        identity["exomiser_manifest"],
    ):
        if current_inputs[manifest_input].stat().st_size <= 0:
            raise Track1Error(f"Required provenance manifest is empty: {manifest_input}")

    gated_manifest_path = current_inputs[GATED_MANIFEST_INPUT]
    try:
        current_gated_dataset = json.loads(gated_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Track1Error("Current gated dataset manifest is unreadable or invalid") from exc
    if gated_dataset != current_gated_dataset:
        raise Track1Error("Final run manifest embeds stale gated dataset provenance")
    return manifest
