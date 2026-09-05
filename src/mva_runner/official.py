"""Pin the public challenge instructions and unmodified submission templates."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now
from mva_track1.resources import _download

ROOT = PROJECT_ROOT / "resources/public/hackathon"
REPOSITORY = "SageBio/rare-disease-real-kid-mva-hackathon-2026"
SOURCE_FILES = {"tabs/rules.py", "tabs/submit_track1.py", "tabs/submit_track2.py", "config.py", "README.md"}


def _selected(name: str) -> bool:
    path = PurePosixPath(name)
    return (not path.is_absolute() and str(path) == name and ".." not in path.parts
            and (name in SOURCE_FILES or name.startswith("static/templates/")))


def _upstream_files(info) -> dict:
    """Keep upstream blob/LFS digests, not just hashes of our cached copy."""
    files = {}
    for sibling in info.siblings:
        if not _selected(sibling.rfilename):
            continue
        lfs = sibling.lfs
        digest = (lfs.get("sha256") if isinstance(lfs, dict) else getattr(lfs, "sha256", None)) if lfs else sibling.blob_id
        algorithm = "sha256" if lfs else "git_blob_sha1"
        if not isinstance(sibling.size, int) or not 0 <= sibling.size <= 20_000_000:
            raise Track1Error("Unexpected official source size; inspect the upstream inventory")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{" + ("64" if lfs else "40") + "}", digest):
            raise Track1Error("Official source lacks a usable upstream content digest")
        files[sibling.rfilename] = {"size": sibling.size, "digest": digest, "algorithm": algorithm}
    if "static/templates/methods_description_form.xlsx" not in files:
        raise Track1Error("Official methods workbook is absent from the upstream inventory")
    return files


def _verify_content(target: Path, expected: dict) -> None:
    if target.is_symlink() or not target.resolve().is_relative_to(ROOT.resolve()):
        raise Track1Error("Official source cache contains an unsafe path")
    if target.stat().st_size != expected["size"]:
        raise Track1Error("Official source cache differs from upstream size; preserve and investigate")
    raw = target.read_bytes()
    digest = (hashlib.sha256(raw).hexdigest() if expected["algorithm"] == "sha256" else
              hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest())
    if digest != expected["digest"]:
        raise Track1Error("Official source cache differs from upstream checksum; preserve and investigate")


def prepare() -> None:
    from huggingface_hub import HfApi
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "source_lock.json"
    api = HfApi(token=False)
    current = api.repo_info(REPOSITORY, repo_type="space", files_metadata=True)
    current_files = _upstream_files(current)
    if lock.exists():
        source = load_jsonish(lock)
        if (source.get("repository") != REPOSITORY or
                not re.fullmatch(r"[0-9a-f]{40}", str(source.get("revision", ""))) or
                not isinstance(source.get("files"), list) or
                any(not isinstance(name, str) or not _selected(name) for name in source["files"])):
            raise Track1Error("Invalid official source lock; preserve and investigate")
        pinned = current if source["revision"] == current.sha else api.repo_info(
            REPOSITORY, repo_type="space", revision=source["revision"], files_metadata=True)
        if pinned.sha != source["revision"]:
            raise Track1Error("Official pinned revision could not be verified")
        expected_files = _upstream_files(pinned)
        if set(source["files"]) != set(expected_files) or len(source["files"]) != len(expected_files):
            raise Track1Error("Official source lock inventory differs from the pinned revision")
    else:
        expected_files = current_files
        source = {"repository": REPOSITORY, "revision": current.sha, "files": sorted(expected_files), "retrieved_at": utc_now()}
        atomic_write_json(lock, source, mode=0o644)
    # Do not silently upgrade official requirements under an existing analysis.
    # Unrelated upstream commits are harmless only when all selected source
    # bytes and inventory are unchanged. Record changes before stopping.
    changed = sorted(name for name in set(expected_files) | set(current_files)
                     if expected_files.get(name) != current_files.get(name))
    freshness = {"checked_at": utc_now(), "pinned_revision": source["revision"],
                 "current_revision": current.sha, "selected_sources_unchanged": not changed,
                 "changed_paths": changed}
    atomic_write_json(ROOT / "current_requirements_check.json", freshness, mode=0o644)
    if changed:
        raise Track1Error("Official requirements or templates changed; review before updating the pinned lock")
    receipts = {}
    for name in source["files"]:
        target = ROOT / name
        if not target.resolve().is_relative_to(ROOT.resolve()) or target.is_symlink():
            raise Track1Error("Official source cache contains an unsafe path")
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/spaces/{REPOSITORY}/resolve/{source['revision']}/{name}"
        if not target.exists():
            _download(url, target)
        _verify_content(target, expected_files[name])
        receipts[name] = {"sha256": sha256_file(target), "size": target.stat().st_size, "url": url,
                          "upstream": expected_files[name]}
    if "static/templates/methods_description_form.xlsx" not in receipts:
        raise Track1Error("Official methods workbook is not available in the pinned challenge repository")
    atomic_write_json(ROOT / "manifest.json", {**source, "artifacts": receipts,
                      "current_requirements_check": freshness}, mode=0o644)


if __name__ == "__main__":
    prepare()
