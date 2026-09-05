from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from .common import PROJECT_ROOT, Track1Error, atomic_write_json, utc_now


FORBIDDEN_PREFIXES = (
    "data/gated/", "work/private/", "results/private/", "logs/", ".snakemake/",
    "config/proband.local.yaml", "config/proband.draft.local.yaml",
    "config/finalists.local.tsv",
    "config/submission.local.json", "config/hf_token.local.txt",
)
FORBIDDEN_NAMES = (
    "Challenge_Clinical_Phenotype_1.docx",
    "WGS_EX2312012_HGWCNDSX7.vcf.gz",
)
PUBLIC_DATA_ALLOWLIST_PREFIXES = (
    "resources/public/reference/",
    "resources/public/vep/",
)
PATIENT_DATA_EXTENSION = re.compile(
    r"(?:"
    r"\.vcf(?:\.(?:gz|bgz))?"
    r"|\.bcf(?:\.gz)?"
    r"|\.bam|\.bai|\.cram|\.crai|\.tbi|\.csi"
    r"|\.(?:fastq|fq)(?:\.(?:gz|bgz|bz2|xz|zst))?"
    r")$",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")
PURGE_TARGETS = (
    "data/gated",
    "work/private",
    "results/private",
    "logs",
    ".snakemake",
    "config/proband.local.yaml",
    "config/proband.draft.local.yaml",
    "config/finalists.local.tsv",
    "config/submission.local.json",
    "config/hf_token.local.txt",
)
GENERATED_SUBMISSION_SUFFIXES = frozenset({".csv", ".md", ".pdf", ".zip"})
GENERATED_SUBMISSION_NAMES = frozenset({"submission_log.tsv"})


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"], cwd=PROJECT_ROOT, capture_output=True, check=False
    )
    if result.returncode != 0:
        raise Track1Error("Privacy audit requires an initialized Git repository")
    return [PROJECT_ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def audit_tracked_files() -> list[str]:
    problems: list[str] = []
    audited: list[str] = []
    root = PROJECT_ROOT.resolve()
    for path in tracked_files():
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            problems.append(f"tracked path escapes project root: {path}")
            continue
        audited.append(rel)
        if rel.startswith(FORBIDDEN_PREFIXES) or any(name in rel for name in FORBIDDEN_NAMES):
            problems.append(f"forbidden tracked path: {rel}")
            continue
        if PATIENT_DATA_EXTENSION.search(rel) and not rel.startswith(
            PUBLIC_DATA_ALLOWLIST_PREFIXES
        ):
            problems.append(f"forbidden tracked patient-data extension: {rel}")
            continue
        if not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if TOKEN_PATTERN.search(text):
            problems.append(f"possible Hugging Face token in: {rel}")
    if problems:
        raise Track1Error("Privacy audit failed:\n- " + "\n- ".join(problems))
    return audited


def purge_preview() -> list[Path]:
    root = PROJECT_ROOT.resolve()
    resolved: list[Path] = []
    for item in PURGE_TARGETS:
        target = (PROJECT_ROOT / item).resolve()
        if target == root or root not in target.parents:
            raise Track1Error(f"Unsafe purge target escaped project root: {target}")
        if target.exists():
            resolved.append(target)
    submissions = PROJECT_ROOT / "submissions"
    if submissions.is_dir():
        for candidate in sorted(submissions.iterdir()):
            if candidate.name == ".gitkeep":
                continue
            if (
                candidate.suffix not in GENERATED_SUBMISSION_SUFFIXES
                and candidate.name not in GENERATED_SUBMISSION_NAMES
            ):
                continue
            if candidate.is_symlink():
                raise Track1Error(
                    f"Unsafe generated submission is a symbolic link: {candidate}"
                )
            if not candidate.is_file():
                continue
            target = candidate.resolve()
            if root not in target.parents:
                raise Track1Error(
                    f"Unsafe generated submission escaped project root: {target}"
                )
            resolved.append(target)
    return resolved


def purge_confirmed(confirmation: str) -> Path:
    if confirmation != "DELETE MVA GATED DATA":
        raise Track1Error("Typed confirmation did not match; nothing was deleted")
    targets = purge_preview()
    deleted: list[str] = []
    for target in targets:
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
        deleted.append(str(target.relative_to(PROJECT_ROOT.resolve())))
    receipt = PROJECT_ROOT / ".mva-data-deletion-receipt.json"
    atomic_write_json(
        receipt,
        {
            "deleted_at": utc_now(),
            "deleted_paths": deleted,
            "retention_deadline": "2026-11-23",
            "organizer_confirmation_email": "RarediseaserealkidMVAhackathon2026@synapse.org",
            "contains_patient_data": False,
        },
        mode=0o644,
    )
    return receipt
