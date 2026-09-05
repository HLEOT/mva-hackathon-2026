from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from .artifacts import (
    FINAL_MANIFEST_REQUIRED_TOOLS,
    validate_final_run_manifest,
    validate_read_validation,
)
from .common import DEFAULT_CONFIG, PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish
from .download import MANIFEST_PATH, SOURCE_DIR, download_group, verify_core
from .phenotype import extract_hpo, validate_proband_config, write_proband_draft
from .privacy import audit_tracked_files, purge_confirmed, purge_preview
from .report import generate_markdown, markdown_to_pdf
from .resources import (
    verify_exomiser_install,
    verify_reference_resources,
    verify_vep_cache,
)
from .submission import (
    build_submission,
    prepare_finalists,
    reviewed_finalists,
    validate_submission_file,
)
from .workflow_tasks import _environment_provenance


CANDIDATES = PROJECT_ROOT / "results" / "private" / "candidates_ranked.tsv"
FINALISTS = PROJECT_ROOT / "config" / "finalists.local.tsv"
VALIDATION = PROJECT_ROOT / "results" / "private" / "read_validation.tsv"
FINAL_RUN_MANIFEST = PROJECT_ROOT / "results" / "private" / "final_run_manifest.json"
SUBMISSION_CONFIG = PROJECT_ROOT / "config" / "submission.local.json"
PROBAND_CONFIG = PROJECT_ROOT / "config" / "proband.local.yaml"


def _snakemake(target: str, cores: int) -> None:
    snakemake = Path(sys.executable).with_name("snakemake")
    if not snakemake.is_file():
        raise Track1Error(
            f"Snakemake executable is absent from the active environment: {snakemake}"
        )
    command = [
        str(snakemake), "--snakefile", "workflow/Snakefile", "--use-conda",
        "--conda-prefix", ".conda/rules", "--cores", str(cores), target,
        "--printshellcmds", "--rerun-incomplete",
    ]
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=env)
    if result.returncode:
        raise Track1Error(f"Snakemake target failed: {target}")


def _hf_username() -> str | None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        return None
    try:
        from huggingface_hub import HfApi

        return str(HfApi(token=token).whoami(token=token)["name"])
    except Exception:
        return None


def _bootstrap_check() -> None:
    (PROJECT_ROOT / "mva-track1").chmod(0o755)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT)
    if result.returncode:
        raise Track1Error("Synthetic tests failed during bootstrap")
    audit_tracked_files()
    print("Bootstrap complete: launcher environment, synthetic tests, and privacy audit passed.")


def _phenotype() -> None:
    verify_core()
    docx = SOURCE_DIR / "Challenge_Clinical_Phenotype_1.docx"
    output = PROJECT_ROOT / "work" / "private" / "phenotype_extracted.tsv"
    private_text = PROJECT_ROOT / "work" / "private" / "phenotype_text_for_review.txt"
    extract_hpo(docx, output, private_text)
    vcf = SOURCE_DIR / "WGS_EX2312012_HGWCNDSX7.vcf.gz"
    draft = PROJECT_ROOT / "config" / "proband.draft.local.yaml"
    suggestions = PROJECT_ROOT / "work" / "private" / "phenotype_suggestions.tsv"
    write_proband_draft(vcf, output, draft, suggestions)
    print("Phenotype extraction and VCF sample discovery completed locally.")
    print(f"Review extracted terms: {output}")
    print(f"Review private source text: {private_text}")
    print(f"Local draft: {draft}")
    print(f"Review suggestions: {suggestions}")
    print("After review, copy the draft to config/proband.local.yaml and replace every placeholder.")


def _submission_identity() -> tuple[str, str]:
    identity = load_jsonish(SUBMISSION_CONFIG)
    username = str(identity.get("hf_username", ""))
    github = str(identity.get("github_url", ""))
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", username) or "REPLACE" in username:
        raise Track1Error("Invalid or placeholder hf_username in submission.local.json")
    match = re.fullmatch(r"https://github\.com/([^/]+)/([^/]+)/?", github)
    if not match:
        raise Track1Error("A canonical public GitHub repository URL is required")
    owner, repository = match.groups()
    if repository.endswith(".git"):
        repository = repository[:-4]
    valid_owner = (
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?", owner)
        and "--" not in owner
    )
    valid_repository = (
        re.fullmatch(r"[A-Za-z0-9._-]{1,100}", repository)
        and repository not in {".", ".."}
    )
    if (
        not valid_owner
        or not valid_repository
        or "replace" in owner.lower()
        or "replace" in repository.lower()
    ):
        raise Track1Error("A non-placeholder GitHub repository URL is required")
    return username, github


def _assert_package_readiness(*, verify_large_hashes: bool = True) -> None:
    """Apply every read-only gate needed before constructing a submission bundle."""
    if not CANDIDATES.is_file() or not VALIDATION.is_file() or not FINAL_RUN_MANIFEST.is_file():
        raise Track1Error("Candidate ranking and raw-read validation must complete before packaging")
    validate_proband_config(PROBAND_CONFIG)
    reviewed_finalists(FINALISTS, CANDIDATES)
    validate_read_validation(VALIDATION, FINALISTS, CANDIDATES)

    environments, tools = _environment_provenance()
    for name in ("scheduler", "launcher", "hts", "annotation", "reads"):
        if environments.get(name, {}).get("status") != "ready":
            raise Track1Error(f"Required environment is not ready: {name}")
    for name in sorted(FINAL_MANIFEST_REQUIRED_TOOLS):
        if tools.get(name, {}).get("status") != "ready":
            raise Track1Error(f"Required tool is not ready: {name}")

    verify_core(write_receipt=False)
    verify_reference_resources()
    verify_vep_cache()
    verify_exomiser_install()
    validate_final_run_manifest(
        FINAL_RUN_MANIFEST,
        VALIDATION,
        verify_large_hashes=verify_large_hashes,
    )


def _package() -> None:
    if not SUBMISSION_CONFIG.exists():
        username = _hf_username() or "REPLACE_WITH_HF_USERNAME"
        atomic_write_json(
            SUBMISSION_CONFIG,
            {"hf_username": username, "github_url": "https://github.com/REPLACE/REPLACE"},
        )
        raise Track1Error(
            "Created config/submission.local.json. Add the public GitHub URL, verify the username, and rerun package."
        )
    username, github = _submission_identity()
    _assert_package_readiness(verify_large_hashes=True)
    slug = username.lower()
    csv_path = PROJECT_ROOT / "submissions" / f"{slug}_track1-ranked.csv"
    md_path = PROJECT_ROOT / "submissions" / f"{slug}_track1_report.md"
    pdf_path = PROJECT_ROOT / "submissions" / f"{slug}_track1_report.pdf"
    zip_path = PROJECT_ROOT / "submissions" / f"{slug}_track1_bundle.zip"
    build_submission(CANDIDATES, FINALISTS, csv_path, VALIDATION)
    validate_submission_file(csv_path)
    generate_markdown(
        CANDIDATES, FINALISTS, VALIDATION,
        FINAL_RUN_MANIFEST, md_path, github,
    )
    markdown_to_pdf(md_path, pdf_path)
    audit_tracked_files()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in (csv_path, md_path, pdf_path):
            archive.write(path, path.name)
    print("Packaged and validated submission artifacts:")
    print(f"CSV submission: {csv_path}")
    print(f"Markdown report: {md_path}")
    print(f"PDF report: {pdf_path}")
    print(f"Convenience ZIP: {zip_path}")


def _validated_state(path: Path, validator=None) -> str:
    if not path.is_file():
        return "WAIT"
    if validator is None:
        return "READY"
    try:
        validator()
    except (Track1Error, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, zipfile.BadZipFile):
        return "INVALID"
    return "READY"


def _environment_state(environments: dict, name: str) -> str:
    status = environments[name]["status"]
    if status == "ready":
        return "READY"
    if status == "environment_incomplete":
        return "INVALID"
    return "WAIT"


def _status() -> None:
    cfg = load_jsonish(DEFAULT_CONFIG)
    reference_fasta = PROJECT_ROOT / cfg["reference"]["fasta"]
    reference = reference_fasta.parent
    bwa_index_files = tuple(
        Path(f"{reference_fasta}.{suffix}")
        for suffix in ("0123", "amb", "ann", "bwt.2bit.64", "pac")
    )
    bwa_index_marker = reference / ".bwa_mem2_complete"
    annotation = cfg["annotation"]
    vep_marker = (
        PROJECT_ROOT
        / annotation["vep_cache_dir"]
        / f".v{annotation['vep_version']}_merged_complete"
    )
    exomiser_marker = PROJECT_ROOT / annotation["exomiser_dir"] / ".complete"
    environments, _tools = _environment_provenance()

    def validate_bwa_index() -> None:
        if not all(path.is_file() and path.stat().st_size > 0 for path in bwa_index_files):
            raise Track1Error("BWA-MEM2 index sidecar is missing or empty")

    checks = {
        "launcher environment": _environment_state(environments, "scheduler"),
        "launcher rule environment": _environment_state(environments, "launcher"),
        "HTS rule environment": _environment_state(environments, "hts"),
        "annotation rule environment": _environment_state(environments, "annotation"),
        "read-validation rule environment": _environment_state(environments, "reads"),
        "HF_TOKEN in environment": "READY" if os.environ.get("HF_TOKEN") else "WAIT",
        "core data and manifest": _validated_state(
            MANIFEST_PATH, lambda: verify_core(write_receipt=False)
        ),
        "private phenotype draft": _validated_state(
            PROJECT_ROOT / "config" / "proband.draft.local.yaml"
        ),
        "reviewed phenotype config": _validated_state(
            PROBAND_CONFIG, lambda: validate_proband_config(PROBAND_CONFIG)
        ),
        "GRCh38 reference": _validated_state(
            reference_fasta, lambda: verify_reference_resources(check_hashes=False)
        ),
        "GRCh38 BWA-MEM2 index": _validated_state(
            bwa_index_marker, validate_bwa_index
        ),
        "VEP merged cache": _validated_state(vep_marker, verify_vep_cache),
        "Exomiser resources": _validated_state(
            exomiser_marker, lambda: verify_exomiser_install(check_hashes=False)
        ),
        "ranked candidates": _validated_state(CANDIDATES),
        "reviewed finalists": _validated_state(
            FINALISTS, lambda: reviewed_finalists(FINALISTS, CANDIDATES)
        ),
        "raw-read validation": _validated_state(
            VALIDATION,
            lambda: validate_read_validation(VALIDATION, FINALISTS, CANDIDATES),
        ),
        "final run manifest": _validated_state(
            FINAL_RUN_MANIFEST,
            lambda: validate_final_run_manifest(
                FINAL_RUN_MANIFEST, VALIDATION, verify_large_hashes=False
            ),
        ),
        "submission identity": _validated_state(SUBMISSION_CONFIG, _submission_identity),
    }
    for label, state in checks.items():
        print(f"{state:7} {label}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="mva-track1")
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap-check")
    sub.add_parser("download-core")
    sub.add_parser("phenotype")
    p = sub.add_parser("run")
    p.add_argument("--cores", type=int, default=32)
    p = sub.add_parser("prepare-public")
    p.add_argument("--cores", type=int, default=32)
    p = sub.add_parser("validate-finalists")
    p.add_argument("--cores", type=int, default=64)
    p = sub.add_parser("package")
    p.add_argument("--cores", type=int, default=8)
    sub.add_parser("status")
    sub.add_parser("test")
    p = sub.add_parser("purge-gated")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--confirm", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "bootstrap-check":
        _bootstrap_check()
    elif args.command == "download-core":
        path = download_group("core")
        verify_core()
        print(f"Downloaded and verified core manifest: {path}")
    elif args.command == "phenotype":
        _phenotype()
    elif args.command == "run":
        _snakemake("prioritise", args.cores)
        if not FINALISTS.exists():
            prepare_finalists(CANDIDATES, FINALISTS)
            print(f"Prepared finalist review: {FINALISTS}")
            print("Review every selected row and replace REVIEW REQUIRED before raw-read validation.")
    elif args.command == "prepare-public":
        _snakemake("public_resources", args.cores)
        verify_reference_resources()
        verify_vep_cache()
        verify_exomiser_install()
        print("Public GRCh38, VEP, and Exomiser resources are ready.")
    elif args.command == "validate-finalists":
        if not CANDIDATES.is_file():
            raise Track1Error("Run candidate prioritisation first")
        if not FINALISTS.exists():
            prepare_finalists(CANDIDATES, FINALISTS)
            raise Track1Error(f"Prepared {FINALISTS}; review it before downloading FASTQs")
        reviewed_finalists(FINALISTS, CANDIDATES)
        download_group("fastq")
        _snakemake("validate_finalists", args.cores)
    elif args.command == "package":
        _package()
    elif args.command == "status":
        _status()
    elif args.command == "test":
        raise SystemExit(subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT).returncode)
    elif args.command == "purge-gated":
        targets = purge_preview()
        if args.dry_run:
            print("Deletion preview:")
            for target in targets:
                print(f"- {target}")
        else:
            print("The following patient-data paths will be permanently deleted:")
            for target in targets:
                print(f"- {target}")
            confirmation = input("Type DELETE MVA GATED DATA to continue: ")
            receipt = purge_confirmed(confirmation)
            print(f"Deletion complete. Receipt: {receipt}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Track1Error as exc:
        raise SystemExit(f"ERROR: {exc}")
