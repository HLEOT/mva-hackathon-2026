"""Pin the public challenge instructions and unmodified submission templates."""
from __future__ import annotations

from pathlib import Path

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now
from mva_track1.resources import _download

ROOT = PROJECT_ROOT / "resources/public/hackathon"
REPOSITORY = "SageBio/rare-disease-real-kid-mva-hackathon-2026"


def prepare() -> None:
    from huggingface_hub import HfApi
    ROOT.mkdir(parents=True, exist_ok=True)
    lock = ROOT / "source_lock.json"
    if lock.exists():
        source = load_jsonish(lock)
    else:
        api = HfApi(token=False)
        info = api.repo_info(REPOSITORY, repo_type="space", files_metadata=True)
        names = [s.rfilename for s in info.siblings if s.rfilename.startswith("static/templates/") or
                 s.rfilename in {"tabs/rules.py", "tabs/submit_track1.py", "tabs/submit_track2.py", "config.py", "README.md"}]
        source = {"repository": REPOSITORY, "revision": info.sha, "files": names, "retrieved_at": utc_now()}
        atomic_write_json(lock, source, mode=0o644)
    receipts = {}
    for name in source["files"]:
        target = ROOT / name
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://huggingface.co/spaces/{REPOSITORY}/resolve/{source['revision']}/{name}"
        if not target.exists():
            _download(url, target)
        receipts[name] = {"sha256": sha256_file(target), "size": target.stat().st_size, "url": url}
    if "static/templates/methods_description_form.xlsx" not in receipts:
        raise Track1Error("Official methods workbook is not available in the pinned challenge repository")
    atomic_write_json(ROOT / "manifest.json", {**source, "artifacts": receipts}, mode=0o644)


if __name__ == "__main__":
    prepare()
