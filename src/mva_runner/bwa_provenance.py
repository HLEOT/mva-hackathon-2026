"""Record a preserved public BWA index and its exact compatible toolchains.

This rule never builds, deletes, touches or rewrites index sidecars. Separating
its receipt from indexing lets unrelated read-QC dependencies evolve without
erasing a previously completed, byte-compatible index.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now
from mva_track1.workflow_tasks import _package_records

SUFFIXES = ("0123", "amb", "ann", "bwt.2bit.64", "pac")


def solved_environment(root: Path, name: str) -> dict:
    definition = root / "workflow/envs" / f"{name}.yaml"
    candidates = [p.with_suffix("") for p in (root / ".conda/rules").glob("*.yaml")
                  if p.read_bytes() == definition.read_bytes() and
                  Path(f"{p.with_suffix('')}.env_setup_done").is_file()]
    if len(candidates) != 1:
        raise Track1Error("BWA provenance requires one exact, completed environment definition")
    prefix = candidates[0]
    packages = _package_records(prefix)
    if packages.get("bwa-mem2", {}).get("version") != "2.2.1":
        raise Track1Error("BWA index/consumer version differs from the approved toolchain")
    binaries = {p.name: sha256_file(p) for p in sorted((prefix / "bin").glob("bwa-mem2*")) if p.is_file()}
    if "bwa-mem2" not in binaries:
        raise Track1Error("The solved BWA toolchain has no executable")
    return {"definition": str(definition.relative_to(root)), "definition_sha256": sha256_file(definition),
            "prefix": str(prefix.relative_to(root)), "packages": packages, "bwa_executable_sha256": binaries}


def verify_contigs(reference: Path) -> int:
    """BWA .ann names, lengths and offsets must describe the indexed FASTA.

    The .ann offset is a zero-based offset in the concatenated reference, not
    a genomic variant coordinate. This check covers every reference contig.
    """
    fai = [(fields[0], int(fields[1])) for line in Path(f"{reference}.fai").read_text().splitlines()
           if (fields := line.split("\t")) and len(fields) >= 2]
    with Path(f"{reference}.ann").open() as handle:
        header = handle.readline().split()
        if len(header) != 3 or int(header[0]) != sum(length for _, length in fai) or int(header[1]) != len(fai):
            raise Track1Error("BWA index header does not match the reference inventory")
        offset = 0
        for name, length in fai:
            label, location = handle.readline().split(), handle.readline().split()
            if len(label) < 2 or len(location) != 3 or label[1] != name or int(location[0]) != offset or int(location[1]) != length:
                raise Track1Error("BWA index contig identity or coordinate layout differs from the reference")
            offset += length
        if handle.read().strip():
            raise Track1Error("BWA index has unexpected extra contig records")
    return len(fai)


def record(reference: Path, output: Path, root: Path = PROJECT_ROOT) -> dict:
    reference = reference.resolve()
    if not reference.is_relative_to(root.resolve()):
        raise Track1Error("BWA reference must remain inside the project")
    expected = load_jsonish(root / "resources/public/manifest.json")["reference"]["files"]
    reference_records = {}
    for path in [reference, Path(f"{reference}.fai")]:
        name = str(path.relative_to(root))
        digest = sha256_file(path)
        if name not in expected or digest != expected[name]["sha256"] or path.stat().st_size != expected[name]["size"]:
            raise Track1Error("BWA reference differs from the verified public reference manifest")
        reference_records[name] = {"size": path.stat().st_size, "sha256": digest}
    indexes = [Path(f"{reference}.{suffix}") for suffix in SUFFIXES]
    if not all(p.is_file() and not p.is_symlink() and p.stat().st_size > 0 for p in indexes):
        raise Track1Error("BWA sidecars are missing, empty or symlinked; existing files are preserved")
    producer, consumer = solved_environment(root, "bwa_index"), solved_environment(root, "reads")
    if producer["bwa_executable_sha256"] != consumer["bwa_executable_sha256"]:
        raise Track1Error("BWA index and alignment executables differ; compatibility requires investigation")
    contigs = verify_contigs(reference)
    before = {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in indexes}
    hashes = {str(p.relative_to(root)): {"size": p.stat().st_size, "sha256": sha256_file(p)} for p in indexes}
    if before != {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in indexes}:
        raise Track1Error("BWA index changed during provenance verification")
    receipt = {"schema_version": 1, "verified_at": utc_now(), "operation": "verify_existing_index_without_modification",
               "reference": reference_records, "index_files": hashes, "reference_contigs_verified": contigs,
               "index_toolchain": producer, "alignment_toolchain": consumer, "bwa_executables_identical": True,
               "limitations": ["Contig/layout and checksum checks are not a de novo reconstruction of the index."]}
    atomic_write_json(output, receipt, mode=0o644)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    record(args.reference, args.output)
