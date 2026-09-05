"""Prepare a pinned local speech executable without modifying the host OS."""
import subprocess

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, sha256_file, utc_now
from mva_track1.resources import _download

VERSION = "1.51+dfsg-12build1"
SHA256 = "ffeac730f1f43b5cdbca708a8215d6b7310bf3bd40d7dcf0affd6a62f86aa6df"
DIRECTORY = PROJECT_ROOT / ".tools/espeak-ng"
BINARY = DIRECTORY / "usr/bin/espeak-ng"


def prepare() -> None:
    directory = PROJECT_ROOT / ".tools"
    archive = directory / f"espeak-ng_{VERSION}_amd64.deb"
    if not archive.exists():
        _download(f"https://archive.ubuntu.com/ubuntu/pool/universe/e/espeak-ng/{archive.name}", archive)
    if sha256_file(archive) != SHA256:
        raise Track1Error("Narration executable package checksum mismatch")
    if not BINARY.exists():
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dpkg-deb", "--extract", str(archive), str(DIRECTORY)], check=True)
    libraries = subprocess.run(["ldd", str(BINARY)], capture_output=True, text=True, check=True)
    if "not found" in libraries.stdout:
        raise Track1Error("Local speech executable requires unavailable host libraries")
    version = subprocess.run([str(BINARY), "--version"], capture_output=True, text=True, check=True)
    atomic_write_json(PROJECT_ROOT / "work/private/runner/speech_runtime.json", {
        "created_at": utc_now(), "package_version": VERSION, "package_sha256": SHA256,
        "binary_sha256": sha256_file(BINARY), "version": version.stdout, "host_libraries": libraries.stdout})


if __name__ == "__main__":
    prepare()
