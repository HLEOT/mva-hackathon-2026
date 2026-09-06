"""Space-aware housekeeping with an explicit allowlist and durable receipts.

Never delete source reads, alignments, indexed resources, review evidence, or
environments to make room. Download archives are removable only after installed
payload verification. Physical accounting counts hard links once; GiB and
decimal disk bytes are intentionally not interchangeable.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import stat
import zipfile
import zlib
from contextlib import contextmanager
from pathlib import Path

import psutil

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, ensure_private_dir, load_jsonish, sha256_file, utc_now
from .storage import allocated_bytes

DISPOSABLE = (".tools/pip-cache", ".pytest_cache",
              "work/private/synthetic_pitch", "work/private/pitch_renderer_recovery_smoke")


def safe_path(root: Path, relative: str) -> Path:
    """Reject broad targets, traversal and symlink ancestors before touching data."""
    candidate = Path(relative)
    if candidate.is_absolute() or not candidate.parts or any(p in {".", ".."} for p in candidate.parts):
        raise Track1Error("Unsafe cleanup target")
    path = root / candidate
    if path == root or any(p.is_symlink() for p in (path, *path.parents)):
        raise Track1Error("Cleanup refuses symlinks or a broad root")
    if not path.resolve().is_relative_to(root.resolve()):
        raise Track1Error("Cleanup target escapes project")
    return path


@contextmanager
def idle_project(root: Path, *, owned_supervisor: bool = False):
    """Serialize against the runner and refuse surviving or independent workers."""
    from .supervisor import is_live, read_state
    runner = ensure_private_dir(root / "work/private/runner")
    lock = None
    if not owned_supervisor:
        lock = (runner / "run.lock").open("a+")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock.close()
            raise Track1Error("Cleanup refused: runner owns the project") from exc
    try:
        state = read_state(runner / "state.json")
        owner = state.get("supervisor")
        if is_live(owner) and (not owned_supervisor or owner["pid"] != os.getpid()):
            raise Track1Error("Cleanup refused: supervisor is live")
        if any(is_live(record.get("child")) for record in state.get("stages", {}).values()):
            raise Track1Error("Cleanup refused: scientific worker is live")
        # A one-off installer or detached recovery worker may not be in state.
        excluded = {os.getpid(), *(p.pid for p in psutil.Process().parents())}
        broker = Path("/usr/local/lib/node_modules/@openai/codex/node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl/bin/codex-code-mode-host")
        for process in psutil.process_iter(["pid", "cwd"]):
            try:
                cwd = process.info.get("cwd")
                if process.pid not in excluded and cwd and Path(cwd).is_relative_to(root):
                    # The verified interactive tool broker is not an analysis
                    # worker. Its independently spawned workers are still scanned.
                    if Path(process.exe()) == broker:
                        continue
                    raise Track1Error("Cleanup refused: another project process is live")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        yield
    finally:
        if lock is not None:
            lock.close()


def _identity(path: Path) -> tuple:
    record = path.lstat()
    return (record.st_dev, record.st_ino, record.st_size, record.st_mtime_ns, record.st_mode)


def _remove_files(root: Path, paths: list[Path], kind: str, *, apply: bool) -> dict:
    """Resolve exact regular files and journal before unlinking. No recursive rm."""
    records = []
    for path in sorted(set(paths)):
        path = safe_path(root, str(path.relative_to(root)))
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise Track1Error("Cleanup target is not a regular file")
        records.append({"path": str(path.relative_to(root)), "identity": _identity(path),
                        "size": metadata.st_size, "allocated_bytes": metadata.st_blocks * 512,
                        "hard_links": metadata.st_nlink})
    receipt = {"created_at": utc_now(), "kind": kind, "status": "planned" if apply else "dry_run",
               "files": records, "removed_files": 0, "reclaimed_bytes": 0,
               "estimated_reclaimable_bytes": sum(r["allocated_bytes"] for r in records if r["hard_links"] == 1)}
    if not apply or not records:
        return receipt
    journal = ensure_private_dir(root / "work/private/runner/cleanup") / (
        utc_now().replace(":", "-") + "_" + kind + ".json")
    before = allocated_bytes(root)
    atomic_write_json(journal, receipt)
    try:
        for record in records:
            path = safe_path(root, record["path"])
            if _identity(path) != record["identity"]:
                raise Track1Error("Cleanup target changed after inventory")
            path.unlink()
            receipt["removed_files"] += 1
        receipt["status"] = "complete"
    except Exception:
        receipt["status"] = "interrupted"
        raise
    finally:
        receipt["reclaimed_bytes"] = max(0, before - allocated_bytes(root))
        receipt["finished_at"] = utc_now()
        atomic_write_json(journal, receipt)
    return receipt


def clean_disposable(*, apply: bool = False, root: Path = PROJECT_ROOT,
                     owned_supervisor: bool = False) -> dict:
    """Routine cleanup is deliberately narrow; unknown scratch stays untouched."""
    with idle_project(root, owned_supervisor=owned_supervisor):
        files, directories = [], []
        for relative in DISPOSABLE:
            target = safe_path(root, relative)
            if not target.exists():
                continue
            if not target.is_dir():
                raise Track1Error("Disposable cache root is not a directory")
            directories.append(target)
            for path in target.rglob("*"):
                safe_path(root, str(path.relative_to(root)))
                (directories if path.is_dir() else files).append(path)
        receipt = _remove_files(root, files, "disposable", apply=apply)
        if apply:
            for directory in sorted(set(directories), key=lambda p: len(p.parts), reverse=True):
                safe_path(root, str(directory.relative_to(root))).rmdir()
        return receipt


def verify_installed_payload(root: Path, *, check_hashes: bool) -> None:
    """Check installed Exomiser files when redundant ZIP downloads were pruned."""
    receipt = load_jsonish(root / "archive_compaction.json")
    payload = root / "installed_payload.json"
    if (receipt.get("install_manifest_sha256") != sha256_file(root / "install_manifest.json")
            or receipt.get("payload_sha256") != sha256_file(payload)):
        raise Track1Error("Installed-resource compaction provenance changed")
    data = load_jsonish(payload)
    if not data.get("files") or data.get("archives") != load_jsonish(root / "install_manifest.json")["archives"]:
        raise Track1Error("Installed-resource inventory is absent or mismatched")
    for record in data["files"]:
        path = safe_path(root, record["path"])
        if not path.is_file() or path.stat().st_size != record["size"]:
            raise Track1Error("Installed resource size mismatch")
        if check_hashes and sha256_file(path) != record["sha256"]:
            raise Track1Error("Installed resource checksum mismatch")


def compact_exomiser(root: Path, *, apply: bool) -> dict:
    """Verify extracted bytes against ZIP CRCs, then retain SHA-256 inventories.

    Read in bounded chunks. This creates only small manifests, not another
    full-size backup. The original URLs and archive hashes remain unchanged.
    """
    manifest_path = root / "install_manifest.json"
    manifest = load_jsonish(manifest_path)
    archives = [safe_path(root, "downloads/" + record["file"]) for record in manifest["archives"]]
    if not apply:
        return {"archive_count": sum(p.is_file() for p in archives),
                "archive_bytes": sum(p.stat().st_size for p in archives if p.is_file())}
    if (root / "archive_compaction.json").exists():
        if any(p.exists() for p in archives):
            verify_installed_payload(root, check_hashes=True)
        return _remove_files(PROJECT_ROOT, [p for p in archives if p.exists()], "exomiser_archives", apply=True)
    files = {}
    cli = root / f"exomiser-cli-{manifest['version']}"
    for archive, source in zip(archives, manifest["archives"]):
        if archive.stat().st_size != source["size"] or sha256_file(archive) != source["sha256"]:
            raise Track1Error("Refusing compaction of an unverified Exomiser archive")
        destination = root if source["file"].startswith("exomiser-cli-") else cli / "data"
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                if member.is_dir():
                    continue
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise Track1Error("Refusing symbolic link in archive")
                path = safe_path(destination, member.filename)
                if not path.is_file() or path.stat().st_size != member.file_size:
                    raise Track1Error("Extracted resource does not match archive size")
                digest, crc = hashlib.sha256(), 0
                identity = _identity(path)
                with path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
                        digest.update(chunk)
                        crc = zlib.crc32(chunk, crc)
                if crc != member.CRC or _identity(path) != identity:
                    raise Track1Error("Extracted resource does not match archive CRC or changed")
                relative = str(path.relative_to(root))
                files[relative] = {"path": relative, "size": member.file_size, "sha256": digest.hexdigest()}
    payload = root / "installed_payload.json"
    atomic_write_json(payload, {"created_at": utc_now(), "archives": manifest["archives"], "files": list(files.values())}, mode=0o644)
    atomic_write_json(root / "archive_compaction.json", {"created_at": utc_now(),
        "install_manifest_sha256": sha256_file(manifest_path), "payload_sha256": sha256_file(payload),
        "policy": "Installed files matched original ZIP sizes and CRCs before archive deletion; SHA-256 retained."}, mode=0o644)
    return _remove_files(PROJECT_ROOT, archives, "exomiser_archives", apply=True)


def compact_resources(*, apply: bool = False) -> dict:
    """Explicit heavier maintenance, not an expensive hash pass every heartbeat."""
    from mva_track1.resources import verify_exomiser_install, verify_vep_cache
    with idle_project(PROJECT_ROOT):
        verify_exomiser_install(check_hashes=False)
        verify_vep_cache()
        cfg = load_jsonish(PROJECT_ROOT / "config/config.yaml")["annotation"]
        exomiser = compact_exomiser(safe_path(PROJECT_ROOT, cfg["exomiser_dir"]), apply=apply)
        vep = safe_path(PROJECT_ROOT, cfg["vep_cache_dir"])
        archive = safe_path(vep, f"downloads/homo_sapiens_merged_vep_{cfg['vep_version']}_GRCh38.tar.gz")
        if apply and archive.is_file():
            manifest = load_jsonish(vep / "install_manifest.json")
            # VEP verifies the installed shard/index inventory, not this archive.
            # Its successful installation and offline annotation are preserved.
            atomic_write_json(vep / "archive_compaction.json", {"created_at": utc_now(),
                "archive": archive.name, "size": archive.stat().st_size, "sha256": sha256_file(archive),
                "source_url": manifest["release_url"], "install_manifest_sha256": sha256_file(vep / "install_manifest.json"),
                "validation": "Installed cache passed VEP metadata, shard/index and manifest inventory checks."}, mode=0o644)
        vep_result = _remove_files(PROJECT_ROOT, [archive] if archive.exists() else [], "vep_archive", apply=apply)
        return {"exomiser": exomiser, "vep": vep_result}
