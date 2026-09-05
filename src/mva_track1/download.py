from __future__ import annotations

import gzip
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

from .common import (
    DEFAULT_CONFIG,
    PROJECT_ROOT,
    Track1Error,
    atomic_write_json,
    ensure_private_dir,
    load_jsonish,
    run_checked,
    sha256_file,
    utc_now,
)


GATED_ROOT = PROJECT_ROOT / "data" / "gated"
SOURCE_DIR = GATED_ROOT / "source"
MANIFEST_PATH = GATED_ROOT / "manifest.json"


def _token() -> str:
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        raise Track1Error(
            "HF_TOKEN is not set. Export an approved read token in this shell; "
            "the workflow will not persist it."
        )
    return token


def _metadata(sibling: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "filename": sibling.rfilename,
        "size": getattr(sibling, "size", None),
        "blob_id": getattr(sibling, "blob_id", None),
    }
    lfs = getattr(sibling, "lfs", None)
    if lfs:
        record["lfs"] = {
            "sha256": getattr(lfs, "sha256", None),
            "size": getattr(lfs, "size", None),
            "pointer_size": getattr(lfs, "pointer_size", None),
        }
    return record


def _validated_download_record(
    local: Path,
    metadata: dict[str, Any],
    group: str,
) -> dict[str, Any]:
    record = dict(metadata)
    expected_size = record.get("size") or record.get("lfs", {}).get("size")
    observed_size = local.stat().st_size
    if expected_size is not None and int(expected_size) != observed_size:
        raise Track1Error(
            f"Size mismatch for {local.name}: expected {expected_size}, got {observed_size}"
        )
    observed_sha256 = sha256_file(local)
    upstream_sha256 = record.get("lfs", {}).get("sha256")
    if upstream_sha256 and observed_sha256 != str(upstream_sha256).lower():
        raise Track1Error(
            f"Upstream LFS SHA-256 mismatch for {local.name}; downloaded file retained"
        )
    record.update(
        {
            "local_path": str(local.resolve().relative_to(PROJECT_ROOT)),
            "downloaded_size": observed_size,
            "sha256": observed_sha256,
            "group": group,
        }
    )
    return record


def _verify_gzip(path: Path) -> None:
    try:
        with gzip.open(path, "rb") as handle:
            while handle.read(8 * 1024 * 1024):
                pass
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise Track1Error(f"Corrupt gzip file: {path.name}") from exc


def download_group(group: str, config_path: Path | str = DEFAULT_CONFIG) -> Path:
    if group not in {"core", "fastq"}:
        raise Track1Error(f"Unknown download group: {group}")
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError as exc:
        raise Track1Error("Run ./mva-track1 bootstrap before downloading data.") from exc

    cfg = load_jsonish(config_path)
    hf_cfg = cfg["huggingface"]
    filenames = hf_cfg["core_files" if group == "core" else "fastq_files"]
    token = _token()
    ensure_private_dir(GATED_ROOT)
    ensure_private_dir(SOURCE_DIR)

    existing = load_jsonish(MANIFEST_PATH) if MANIFEST_PATH.exists() else {}
    if existing and (existing.get("repo_id") != hf_cfg["repo_id"] or existing.get("repo_type") != hf_cfg["repo_type"]):
        raise Track1Error("Existing gated manifest belongs to a different repository")
    api = HfApi(token=token)
    try:
        info = api.dataset_info(
            repo_id=hf_cfg["repo_id"], files_metadata=True, token=token,
            revision=existing.get("revision")
        )
    except Exception as exc:
        raise Track1Error(
            "Unable to read the gated dataset. Confirm that this Hugging Face "
            "account accepted the rules and that HF_TOKEN belongs to it."
        ) from exc

    available = {item.rfilename: item for item in info.siblings}
    missing = sorted(set(filenames) - set(available))
    if missing:
        raise Track1Error(f"Expected dataset files are missing: {', '.join(missing)}")

    existing: dict[str, Any] = {}
    if MANIFEST_PATH.exists():
        existing = load_jsonish(MANIFEST_PATH)
        existing_revision = existing.get("revision")
        if existing_revision != info.sha:
            raise Track1Error(
                "Refusing to mix Hugging Face dataset revisions: the existing "
                f"manifest records {existing_revision!r}, but the repository now "
                f"resolves to {info.sha!r}. Run `./mva-track1 purge-gated --dry-run`, "
                "then `./mva-track1 purge-gated --confirm`, and redownload the core "
                "group before adding further files."
            )
    manifest: dict[str, Any] = {
        "repo_id": hf_cfg["repo_id"],
        "repo_type": hf_cfg["repo_type"],
        "revision": info.sha,
        "downloaded_at": utc_now(),
        "files": existing.get("files", {}),
    }

    for filename in filenames:
        local = Path(
            hf_hub_download(
                repo_id=hf_cfg["repo_id"],
                filename=filename,
                repo_type=hf_cfg["repo_type"],
                revision=info.sha,
                local_dir=SOURCE_DIR,
                token=token,
            )
        )
        item = _validated_download_record(local, _metadata(available[filename]), group)
        manifest["files"][filename] = item
        atomic_write_json(MANIFEST_PATH, manifest)

    return MANIFEST_PATH


def verify_core(
    config_path: Path | str = DEFAULT_CONFIG,
    *,
    write_receipt: bool = True,
) -> dict[str, Any]:
    cfg = load_jsonish(config_path)
    if not MANIFEST_PATH.exists():
        raise Track1Error("Core manifest is absent; run ./mva-track1 download-core.")
    manifest = load_jsonish(MANIFEST_PATH)
    outcomes: dict[str, Any] = {"verified_at": utc_now(), "files": {}}

    for filename in cfg["huggingface"]["core_files"]:
        path = SOURCE_DIR / filename
        if not path.is_file():
            raise Track1Error(f"Missing core file: {path}")
        recorded = manifest.get("files", {}).get(filename)
        if not recorded:
            raise Track1Error(f"No manifest record for {filename}")
        actual_sha = sha256_file(path)
        if actual_sha != recorded["sha256"]:
            raise Track1Error(f"SHA-256 mismatch for {filename}")
        outcomes["files"][filename] = {
            "size": path.stat().st_size,
            "sha256": actual_sha,
        }

    docx = SOURCE_DIR / "Challenge_Clinical_Phenotype_1.docx"
    with zipfile.ZipFile(docx) as archive:
        bad_member = archive.testzip()
        if bad_member:
            raise Track1Error(f"Corrupt DOCX member: {bad_member}")

    vcf = SOURCE_DIR / "WGS_EX2312012_HGWCNDSX7.vcf.gz"
    _verify_gzip(vcf)
    if not (SOURCE_DIR / "WGS_EX2312012_HGWCNDSX7.vcf.gz.tbi").stat().st_size:
        raise Track1Error("VCF index is empty")
    if shutil.which("bcftools") is None:
        outcomes["bcftools_index_check"] = "deferred: bcftools is not installed"
    else:
        result = run_checked(["bcftools", "index", "-n", str(vcf)])
        outcomes["vcf_records"] = int(result.stdout.strip())

    if write_receipt:
        output = PROJECT_ROOT / "work" / "private" / "core_verified.json"
        ensure_private_dir(output.parent)
        atomic_write_json(output, outcomes)
    return outcomes
