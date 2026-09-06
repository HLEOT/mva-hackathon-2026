"""Read-only prerequisites: expose status categories, never credentials or evidence."""
from __future__ import annotations

import os
import re
import shutil

import psutil
import requests

from mva_track1.cli import readiness
from mva_track1.common import PROJECT_ROOT, load_jsonish
from .storage import require_space


def limits_valid(limits: dict) -> bool:
    """A configuration edit cannot silently enlarge the user's authorisation."""
    values = [limits.get(key) for key in ("cpus", "memory_gib", "additional_disk_bytes", "disk_reserve_bytes")]
    if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
        return False
    cpus, memory, disk, reserve = values
    # The user explicitly raised only the additional-disk allowance on 2026-09-05.
    return 1 <= cpus <= 112 and 1 <= memory <= 400 and 0 < disk <= 400_000_000_000 and 0 <= reserve < disk


def probe_gated_file(dataset: dict, token: str, revision: str) -> bool:
    """A HEAD metadata request tests gated file access without fetching content."""
    from huggingface_hub import get_hf_file_metadata, hf_hub_url
    names = dataset.get("core_files", [])
    if not names or not re.fullmatch(r"[0-9a-f]{40}", revision):
        return False
    metadata = get_hf_file_metadata(hf_hub_url(dataset["repo_id"], names[0], repo_type="dataset", revision=revision),
                                    token=token, timeout=20)
    return metadata.commit_hash == revision and isinstance(metadata.size, int) and metadata.size > 0


def hf_authentication(expected_username: str, dataset: dict) -> dict:
    """Verify identity and gated metadata with bounded, non-redirecting requests.

    Only a public dataset identifier and the token's normal authentication
    header leave the host. No patient records or phenotype fields are queried.
    """
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        return {"status": "missing_token"}
    repo_id = dataset.get("repo_id", "")
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repo_id):
        return {"status": "invalid_dataset_identifier"}
    headers = {"Authorization": "Bearer " + token}
    try:
        identity = requests.get("https://huggingface.co/api/whoami-v2", headers=headers,
                                timeout=(10, 20), allow_redirects=False)
        if identity.status_code != 200:
            return {"status": "identity_not_verified", "http_status": identity.status_code}
        if identity.json().get("name") != expected_username:
            return {"status": "identity_mismatch"}
        response = requests.get("https://huggingface.co/api/datasets/" + repo_id, headers=headers,
                                timeout=(10, 20), allow_redirects=False)
        if response.status_code != 200:
            return {"status": "dataset_access_not_verified", "http_status": response.status_code}
        metadata = response.json()
        if metadata.get("id") != repo_id:
            return {"status": "dataset_identity_mismatch"}
        manifest_path = PROJECT_ROOT / "data/gated/manifest.json"
        manifest = load_jsonish(manifest_path) if manifest_path.is_file() else {}
        revision = manifest.get("revision") or metadata.get("sha", "")
        if not probe_gated_file(dataset, token, revision):
            return {"status": "gated_file_access_not_verified"}
        return {"status": "verified", "identity_matches": True, "dataset_metadata_access": True,
                "pinned_file_metadata_access": True}
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        return {"status": "verification_failed", "error_category": type(exc).__name__}


def github_destination(repository: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repository):
        return {"status": "invalid_repository_identifier"}
    try:
        response = requests.get("https://api.github.com/repos/" + repository, timeout=(10, 20), allow_redirects=False)
        if response.status_code != 200:
            return {"status": "not_verified", "http_status": response.status_code}
        data = response.json()
        if data.get("full_name") != repository or data.get("private") is not False:
            return {"status": "public_destination_mismatch"}
        return {"status": "public_destination_verified", "write_access": "checked_separately_by_authenticated_publisher"}
    except (requests.RequestException, ValueError, TypeError, AttributeError) as exc:
        return {"status": "verification_failed", "error_category": type(exc).__name__}


def collect(cfg: dict, *, offline: bool = False) -> dict:
    from .codex_review import pending_reviews, terms_confirmed
    report = {"configuration_within_authorisation": limits_valid(cfg["limits"]),
              "limits": cfg["limits"], "storage": require_space(),
              "host": {"available_cpus": len(os.sched_getaffinity(0)), "physical_memory_bytes": psutil.virtual_memory().total}}
    try:
        report["scientific_readiness"] = readiness()
    except Exception as exc:
        report["scientific_readiness"] = {"readiness_check": "INVALID"}
        report["readiness_error_category"] = type(exc).__name__
    scientific = load_jsonish(PROJECT_ROOT / "config/config.yaml")
    token_file = PROJECT_ROOT / "config/hf_token.local.txt"
    report["token_file_owner_only"] = not token_file.exists() or (
        token_file.stat().st_uid == os.getuid() and token_file.stat().st_mode & 0o077 == 0)
    # Never transmit a credential from an insecure file merely to test it.
    report["huggingface"] = ({"status": "not_checked_offline"} if offline else
        hf_authentication(cfg["delivery"]["hf_username"], scientific["huggingface"]) if report["token_file_owner_only"] else
        {"status": "insecure_token_file"})
    report["github"] = ({"status": "not_checked_offline"} if offline else
                         github_destination(cfg["delivery"]["github_repository"]))
    report["interpretation"] = {"reviewer": "active Codex session", "local_inference_required": False,
        "private_review_terms_confirmed": terms_confirmed(), "pending_reviews": pending_reviews()}
    report["host_delivery_tools"] = {name: bool(shutil.which(name)) for name in ["tmux", "pdftoppm", "pdftotext"]}
    report["local_delivery_tools"] = {
        "ffmpeg": os.access(PROJECT_ROOT / ".conda/delivery/bin/ffmpeg", os.X_OK),
        "speech": os.access(PROJECT_ROOT / ".tools/espeak-ng/usr/bin/espeak-ng", os.X_OK)}
    disclosure_path = PROJECT_ROOT / "config/ai_usage.local.yaml"
    disclosure = load_jsonish(disclosure_path) if disclosure_path.is_file() else {}
    report["missing_delivery_disclosure_fields"] = [key for key in ["hosted_plan", "hosted_data_setting"] if not str(disclosure.get(key, "")).strip()]
    # Finalists, raw reads and delivery are expected to be incomplete before a
    # first run. Report them, but do not mistake those future outputs for a
    # missing input resource. Rule environments are built by Snakemake on demand.
    required = ["launcher environment", "core data and manifest", "GRCh38 reference", "VEP merged cache", "Exomiser resources"]
    report["missing_base_prerequisites"] = [name for name in required if report["scientific_readiness"].get(name) != "READY"]
    report["base_prerequisites_verified"] = bool(
        report["configuration_within_authorisation"] and report["token_file_owner_only"] and
        not report["missing_base_prerequisites"] and report["huggingface"]["status"] == "verified" and
        report["host_delivery_tools"]["tmux"])
    report["completion_scope"] = "base prerequisites only; scientific and final-delivery acceptance are separate"
    return report
