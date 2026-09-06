"""Run validated scientific stages in private subprocesses with bounded compute."""
from __future__ import annotations

import os
import subprocess
import sys

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now
from mva_track1.download import MANIFEST_PATH, SOURCE_DIR, download_group
from mva_track1.phenotype import validate_proband_config
from mva_track1.submission import reviewed_finalists
from .storage import EXECUTION, require_space


def alignment_threads(total: int) -> dict:
    """Reserve process main threads and decompressors, not just BWA workers.

    Five samtools processes run concurrently. Their -@ values are additional
    workers. Two sorts each use at most (io+1)*8 GiB of buffers. With 96 slots,
    the two buffers total 112 GiB, leaving room for BWA and CRAM processing.
    """
    if total < 16:
        raise Track1Error("Streaming alignment requires at least 16 allocated CPUs")
    workers = total - 12
    bwa = max(1, int(workers * 0.60))
    io_threads = max(0, (workers - bwa) // 5)
    return {"bwa": bwa, "io": io_threads, "accounted_cpus": bwa + 5 * io_threads + 12}


def workflow(target: str) -> None:
    cfg = load_jsonish(EXECUTION)
    # The affinity inherited from the supervisor constrains all descendants;
    # Snakemake additionally accounts for concurrent rules within this limit.
    cores = min(112, int(cfg["limits"]["cpus"]), len(os.sched_getaffinity(0)))
    executable = os.path.join(os.path.dirname(sys.executable), "snakemake")
    command = [executable, "--snakefile", "workflow/Snakefile", "--use-conda",
               "--conda-prefix", ".conda/rules", "--cores", str(cores),
               "--resources", "mem_mb=360000", "--rerun-incomplete", "--printshellcmds", target]
    environment = {**os.environ, "PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1",
                   "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    result = subprocess.run(command, cwd=PROJECT_ROOT, env=environment)
    if result.returncode:
        raise Track1Error("Scientific workflow failed; detailed diagnostics retained only in private logs")


def prioritise() -> None:
    validate_proband_config(PROJECT_ROOT / "config/proband.local.yaml")
    workflow("prioritise")
    atomic_write_json(PROJECT_ROOT / "work/private/runner/prioritisation_verified.json", {
        "checked_at": utc_now(), "candidates_sha256": sha256_file(PROJECT_ROOT / "results/private/candidates_ranked.tsv")})


def download_reads() -> None:
    reviewed_finalists(PROJECT_ROOT / "config/finalists.local.tsv", PROJECT_ROOT / "results/private/candidates_ranked.tsv")
    # Existing complete/partial task downloads already count in the baseline
    # delta, so reserve only the outstanding bytes before restarting transfer.
    cfg = load_jsonish(PROJECT_ROOT / "config/config.yaml")
    present = sum((SOURCE_DIR / name).stat().st_size for name in cfg["huggingface"]["fastq_files"] if (SOURCE_DIR / name).exists())
    partial = sum(path.stat().st_size for path in SOURCE_DIR.glob(".cache/huggingface/download/*.incomplete"))
    require_space(max(0, 84_668_434_104 - present - partial))
    download_group("fastq")
    manifest = load_jsonish(MANIFEST_PATH)
    records = {name: manifest["files"][name] for name in cfg["huggingface"]["fastq_files"]}
    if len(records) != 8 or sum(record["downloaded_size"] for record in records.values()) != 84_668_434_104:
        raise Track1Error("Pinned raw-read inventory differs from the approved storage estimate")
    atomic_write_json(PROJECT_ROOT / "work/private/runner/reads_downloaded.json", {
        "checked_at": utc_now(), "revision": manifest["revision"], "files": records})


def validate_reads() -> None:
    workflow("validate_finalists")
    # Raw evidence must be re-evaluated before delivery. This receipt does not
    # assert causality or trans phase and never edits the measured evidence.
    from .review import reassess_reads
    if reassess_reads():
        workflow("validate_finalists")


def provenance() -> None:
    """Refresh the final scientific snapshot without owning read measurements."""
    workflow("final_run_manifest")
