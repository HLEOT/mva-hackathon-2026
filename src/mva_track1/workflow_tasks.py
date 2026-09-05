from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from .common import (
    PROJECT_ROOT,
    Track1Error,
    atomic_write_json,
    atomic_write_text,
    load_jsonish,
    sha256_file,
    utc_now,
)
from .download import SOURCE_DIR, verify_core
from .exomiser import run_exomiser, write_phenopacket
from .phenotype import extract_hpo, validate_proband_config
from .ranking import rank_vcf
from .resources import (
    create_vep_install_manifest,
    download_reference,
    install_exomiser,
    verify_vep_cache,
)
from .submission import reviewed_finalists
from .validation import validate_finalist_reads, write_finalist_regions
from .vcf import inspect_vcf


_ENVIRONMENT_NAMES = ("launcher", "hts", "annotation", "reads")
_TOOL_PACKAGES = {
    "scheduler.snakemake": ("scheduler", "snakemake-minimal"),
    "launcher_rule.python": ("launcher", "python"),
    "hts.bcftools": ("hts", "bcftools"),
    "hts.samtools": ("hts", "samtools"),
    "annotation.bcftools": ("annotation", "bcftools"),
    "annotation.vep": ("annotation", "ensembl-vep"),
    "annotation.java": ("annotation", "openjdk"),
    "reads.bwa_mem2": ("reads", "bwa-mem2"),
    "reads.samtools": ("reads", "samtools"),
    "reads.bcftools": ("reads", "bcftools"),
    "reads.fastqc": ("reads", "fastqc"),
    "reads.multiqc": ("reads", "multiqc"),
    "reads.mosdepth": ("reads", "mosdepth"),
    "reads.whatshap": ("reads", "whatshap"),
    "reads.seqkit": ("reads", "seqkit"),
    "reads.gzip": ("reads", "gzip"),
    "reads.pysam": ("reads", "pysam"),
}


def _package_records(prefix: Path) -> dict:
    packages = {}
    for metadata_path in sorted((prefix / "conda-meta").glob("*.json")):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        package_name = metadata.get("name")
        if not package_name:
            continue
        packages[package_name] = {
            "version": metadata.get("version", "unknown"),
            "build": metadata.get("build", "unknown"),
            "channel": metadata.get("channel", "unknown"),
        }
    return packages


def _environment_provenance(project_root: Path = PROJECT_ROOT) -> tuple[dict, dict]:
    """Read versions from Snakemake's exact solved Conda environments."""
    definitions = project_root / "workflow" / "envs"
    prefix_root = project_root / ".conda" / "rules"
    solved_definitions = sorted(prefix_root.glob("*.yaml"))
    environments = {}

    scheduler_prefix = project_root / ".conda" / "launcher"
    scheduler_definition = definitions / "launcher.yaml"
    scheduler_record = {
        "definition": str(scheduler_definition.relative_to(project_root)),
        "definition_sha256": sha256_file(scheduler_definition),
        "prefix": str(scheduler_prefix.relative_to(project_root)),
    }
    if not (scheduler_prefix / "conda-meta" / "history").is_file():
        scheduler_record["status"] = "environment_not_built"
    else:
        scheduler_record.update(
            {"status": "ready", "packages": _package_records(scheduler_prefix)}
        )
    environments["scheduler"] = scheduler_record

    for name in _ENVIRONMENT_NAMES:
        definition = definitions / f"{name}.yaml"
        record = {
            "definition": str(definition.relative_to(project_root)),
            "definition_sha256": sha256_file(definition),
        }
        definition_bytes = definition.read_bytes()
        solved = next(
            (
                candidate
                for candidate in solved_definitions
                if candidate.read_bytes() == definition_bytes
            ),
            None,
        )
        if solved is None:
            record["status"] = "environment_not_built"
            environments[name] = record
            continue

        prefix = solved.with_suffix("")
        setup_done = Path(f"{prefix}.env_setup_done")
        if not setup_done.is_file():
            record.update(
                {
                    "status": "environment_incomplete",
                    "prefix": str(prefix.relative_to(project_root)),
                }
            )
            environments[name] = record
            continue
        record.update(
            {
                "status": "ready",
                "prefix": str(prefix.relative_to(project_root)),
                "packages": _package_records(prefix),
            }
        )
        environments[name] = record

    tools = {}
    for tool, (environment_name, package_name) in _TOOL_PACKAGES.items():
        environment = environments[environment_name]
        if environment["status"] != "ready":
            tools[tool] = {
                "status": environment["status"],
                "environment": environment_name,
                "package": package_name,
            }
            continue
        package = environment["packages"].get(package_name)
        if package is None:
            tools[tool] = {
                "status": "package_not_installed",
                "environment": environment_name,
                "package": package_name,
            }
            continue
        tools[tool] = {
            "status": "ready",
            "environment": environment_name,
            "package": package_name,
            **package,
        }
    return environments, tools


def _reference_check(vcf: Path, fai: Path, output: Path, rename_map: Path | None = None) -> None:
    inspected = inspect_vcf(vcf)
    fai_contigs: dict[str, int] = {}
    with fai.open(encoding="utf-8") as handle:
        for line in handle:
            fields = line.split("\t")
            fai_contigs[fields[0]] = int(fields[1])
    mismatches = []
    aliases = {}
    for contig, length in inspected["contigs"].items():
        bare = contig.removeprefix("chr")
        canonical = "chr" + ("M" if bare == "MT" else bare)
        target = contig if contig in fai_contigs else canonical
        if target in fai_contigs:
            aliases[contig] = target
            if length is not None and fai_contigs[target] != length:
                mismatches.append(f"{contig}: VCF={length}, FASTA={fai_contigs[target]}")
    # Renaming is not liftover. A matching length is required when the header
    # specifies one; bcftools then checks each REF base against this assembly.
    primary = [name for name in inspected["contigs"] if name.removeprefix("chr") in {str(i) for i in range(1, 23)} | {"X", "Y", "M", "MT"}]
    absent = [name for name in primary if name not in aliases]
    if mismatches or absent:
        raise Track1Error(
            "Reference does not match VCF header. "
            + ("Length mismatches: " + ", ".join(mismatches[:10]) if mismatches else "")
            + (" Missing contigs: " + ", ".join(absent[:10]) if absent else "")
        )
    if len(set(aliases.values())) != len(aliases):
        raise Track1Error("VCF contains colliding chromosome aliases")
    if rename_map is not None:
        atomic_write_text(rename_map, "".join(f"{old}\t{new}\n" for old, new in aliases.items()))
    atomic_write_json(
        output,
        {
            "checked_at": utc_now(),
            "vcf_reference": inspected["reference"],
            "vcf_samples": inspected["samples"],
            "matched_primary_contigs": len(primary),
            "contig_aliases": aliases,
        },
    )


def _run_manifest(
    output: Path,
    inputs: list[Path],
    project_root: Path = PROJECT_ROOT,
) -> None:
    project_root = project_root.resolve()
    environments, tools = _environment_provenance(project_root)
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        text=True,
        capture_output=True,
    )
    resolved_inputs = [
        (path if path.is_absolute() else project_root / path).resolve()
        for path in inputs
    ]
    core_manifest_path = (project_root / "data" / "gated" / "manifest.json").resolve()
    if core_manifest_path not in resolved_inputs:
        raise Track1Error("Final manifest inputs omit the gated dataset manifest")
    try:
        gated_dataset = json.loads(core_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Track1Error("Gated dataset manifest is unreadable or invalid") from exc
    required_gated_fields = {"repo_id", "repo_type", "revision", "files"}
    if not required_gated_fields.issubset(gated_dataset) or not isinstance(
        gated_dataset["files"], dict
    ):
        raise Track1Error("Gated dataset manifest has an invalid schema")
    try:
        config = load_jsonish(project_root / "config" / "config.yaml")
        assembly = str(config["project"]["assembly"])
        repo_id = str(config["huggingface"]["repo_id"])
        repo_type = str(config["huggingface"]["repo_type"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise Track1Error("Workflow configuration is unreadable or incomplete") from exc
    if (
        gated_dataset.get("repo_id") != repo_id
        or gated_dataset.get("repo_type") != repo_type
    ):
        raise Track1Error("Gated dataset manifest does not match workflow configuration")

    input_records = {}
    for path in resolved_inputs:
        try:
            relative = str(path.relative_to(project_root))
        except ValueError as exc:
            raise Track1Error(f"Manifest input is outside the project: {path}") from exc
        if not path.is_file():
            raise Track1Error(f"Manifest input is missing or not a file: {relative}")
        input_records[relative] = {
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    atomic_write_json(
        output,
        {
            "created_at": utc_now(),
            "git_commit": git.stdout.strip() if git.returncode == 0 else "uncommitted",
            "tools": tools,
            "environments": environments,
            "inputs": input_records,
            "gated_dataset": gated_dataset,
            "privacy_mode": "local-only",
            "assembly": assembly,
        },
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    sub = result.add_subparsers(dest="task", required=True)
    sub.add_parser("verify-core")
    p = sub.add_parser("extract-phenotype")
    p.add_argument("--docx", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--private-text", type=Path, required=True)
    p = sub.add_parser("validate-proband")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("validate-finalists-review")
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--finalists", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("reference")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("reference-check")
    p.add_argument("--vcf", type=Path, required=True)
    p.add_argument("--fai", type=Path, required=True)
    p.add_argument("--rename-map", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("install-exomiser")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("verify-vep-cache")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p = sub.add_parser("phenopacket")
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("exomiser")
    p.add_argument("--vcf", type=Path, required=True)
    p.add_argument("--phenopacket", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("rank")
    p.add_argument("--vcf", type=Path, required=True)
    p.add_argument("--sample", required=True)
    p.add_argument("--exomiser", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("validate-reads")
    p.add_argument("--cram", type=Path, required=True)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--finalists", type=Path, required=True)
    p.add_argument("--phased-vcf", type=Path)
    p.add_argument("--sample")
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("finalist-regions")
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--finalists", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("manifest")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("inputs", nargs="*", type=Path)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.task == "verify-core":
        verify_core()
    elif args.task == "extract-phenotype":
        extract_hpo(args.docx, args.output, args.private_text)
    elif args.task == "validate-proband":
        validate_proband_config(args.config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("reviewed\n", encoding="utf-8")
        args.output.chmod(0o600)
    elif args.task == "validate-finalists-review":
        reviewed_finalists(args.finalists, args.candidates)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("reviewed\n", encoding="utf-8")
        args.output.chmod(0o600)
    elif args.task == "reference":
        fasta = download_reference()
        if fasta.resolve() != args.output.resolve():
            raise Track1Error(f"Reference was written to unexpected path: {fasta}")
    elif args.task == "reference-check":
        _reference_check(args.vcf, args.fai, args.output, args.rename_map)
    elif args.task == "install-exomiser":
        marker = install_exomiser()
        if marker.resolve() != args.output.resolve():
            raise Track1Error(f"Exomiser marker was written to unexpected path: {marker}")
    elif args.task == "verify-vep-cache":
        manifest = create_vep_install_manifest()
        if manifest.resolve() != args.manifest.resolve():
            raise Track1Error(f"VEP manifest was written to unexpected path: {manifest}")
        verify_vep_cache(require_marker=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text("complete\n", encoding="utf-8")
    elif args.task == "phenopacket":
        write_phenopacket(args.config, args.output)
    elif args.task == "exomiser":
        run_exomiser(args.vcf, args.phenopacket, args.output_dir, args.output)
    elif args.task == "rank":
        rank_vcf(args.vcf, args.sample, args.output, args.exomiser)
    elif args.task == "validate-reads":
        validate_finalist_reads(
            args.cram, args.reference, args.candidates, args.finalists, args.output,
            args.phased_vcf, args.sample,
        )
    elif args.task == "finalist-regions":
        write_finalist_regions(args.candidates, args.finalists, args.output)
    elif args.task == "manifest":
        _run_manifest(args.output, args.inputs)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Track1Error as exc:
        raise SystemExit(f"ERROR: {exc}")
