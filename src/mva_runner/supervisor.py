"""Durable stage execution with immutable fingerprints and resource checks.

Private subprocess output is written to owner-readable files. The CLI returns
stage names and error categories only, allowing a hosted coding agent to
monitor work without reading the patient's evidence.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, ensure_private_dir, load_jsonish, sha256_file, utc_now
from .storage import EXECUTION, BudgetExceeded, require_space

STATE_DIR = PROJECT_ROOT / "work/private/runner"
STATE = STATE_DIR / "state.json"


@dataclass(frozen=True)
class Stage:
    name: str
    dependencies: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    estimate_bytes: int = 0


def stages(tracks: str = "both") -> list[Stage]:
    """Track boundaries are explicit so evidence collection can progress early."""
    # Keep rule-file dependencies scoped to the scientific stage. Editing a
    # report renderer must not force a new genome alignment or VEP annotation.
    scientific_inputs = ("src/mva_runner/scientific.py", "src/mva_track1/common.py",
                         "src/mva_track1/workflow_tasks.py")
    prioritisation_rules = tuple("workflow/rules/" + name for name in (
        "00_targets.smk", "10_inputs.smk", "20_resources.smk", "30_annotation.smk",
        "40_prioritisation.smk", "70_provenance.smk"))
    read_rules = tuple("workflow/rules/" + name for name in (
        "00_targets.smk", "20_resources.smk", "50_alignment.smk", "60_validation.smk", "70_provenance.smk"))
    scientific_envs = tuple("workflow/envs/" + name + ".yaml" for name in ("launcher", "hts", "annotation"))
    result = [
        Stage("model", (), ("config/execution.yaml", "src/mva_runner/local.py"),
              ("resources/public/models/install_manifest.json",), 22_000_000_000),
        Stage("public_evidence", (), ("config/track2.yaml", "src/mva_track2/evidence.py", "src/mva_track2/sources.py"),
              ("resources/public/evidence/manifest.json",), 1_000_000_000),
        Stage("phenotype", ("model",), ("data/gated/source/Challenge_Clinical_Phenotype_1.docx",
              "data/gated/source/WGS_EX2312012_HGWCNDSX7.vcf.gz", "src/mva_runner/review.py",
              "prompts/local/phenotype.md"), ("config/proband.local.yaml", "work/private/phenotype_review.json")),
        Stage("prioritise", ("phenotype",), ("config/config.yaml", "workflow/Snakefile",
              "src/mva_track1/vcf.py", "src/mva_track1/ranking.py", "src/mva_track1/exomiser.py")
              + scientific_inputs + prioritisation_rules + scientific_envs,
              ("results/private/candidates_ranked.tsv", "results/private/candidates_baseline.tsv",
               "results/private/run_manifest.json"), 5_000_000_000),
        Stage("finalists", ("prioritise", "model"), ("src/mva_runner/review.py", "prompts/local/finalists.md"),
              ("work/private/finalists_proposed.tsv", "work/private/finalist_review.json")),
        Stage("download_reads", ("finalists",), ("config/config.yaml", "src/mva_track1/download.py"),
              ("work/private/runner/reads_downloaded.json",)),
        Stage("validate_reads", ("download_reads", "finalists"), ("workflow/Snakefile", "src/mva_track1/validation.py",
              "src/mva_runner/read_evidence.py", "src/mva_runner/tasks.py",
              "src/mva_track1/submission.py", "src/mva_runner/review.py", "workflow/envs/reads.yaml",
              "src/mva_runner/bwa_provenance.py", "workflow/envs/bwa_index.yaml")
              + scientific_inputs + read_rules + scientific_envs,
              ("config/finalists.local.tsv", "results/private/read_validation.tsv", "work/private/read_reassessment.json"), 95_000_000_000),
    ]
    if tracks == "both":
        result.append(Stage("track2", ("public_evidence", "validate_reads", "model"),
                      ("config/track2.yaml", "src/mva_track2/analysis.py", "prompts/local/track2.md"),
                      ("results/private/track2/hypotheses.json", "results/private/track2/evidence.tsv")))
    # Provenance owns its manifest independently of the expensive read stage.
    # A renderer/code-release edit updates recorded hashes without requiring a
    # fresh 95 GB alignment reservation or invalidating measured read evidence.
    provenance_sources = tuple(sorted(str(path.relative_to(PROJECT_ROOT))
        for path in (PROJECT_ROOT / "src").rglob("*.py")))
    result.append(Stage("provenance", ("validate_reads",), provenance_sources +
        tuple(sorted(str(path.relative_to(PROJECT_ROOT)) for path in (PROJECT_ROOT / "workflow").rglob("*.smk"))) +
        ("workflow/Snakefile", "config/config.yaml", "config/execution.yaml", "config/track2.yaml",
         "data/gated/manifest.json", "mva", "mva-track1", "pyproject.toml"),
        ("results/private/final_run_manifest.json",), 1_000_000_000))
    if tracks != "both":
        # Track 1 is an explicit scientific-only subset. The unified package
        # always contains both tracks and cannot truthfully run without Track 2.
        return [stage for stage in result if stage.name != "public_evidence"]
    dependencies = ("provenance", "track2")
    result.append(Stage("package", dependencies, ("config/execution.yaml", "config/ai_usage.local.yaml",
                        "src/mva_runner/delivery.py", "src/mva_runner/official.py", "src/mva_runner/render.py", "src/mva_runner/qc.py", "src/mva_runner/read_evidence.py",
                        "src/mva_runner/workbooks.py", "src/mva_runner/pitch.py", "src/mva_runner/speech.py",
                        "src/mva_track1/report.py", "src/mva_track1/submission.py", "workflow/envs/delivery.yaml"),
                        ("submissions/delivery_manifest.json",), 1_000_000_000))
    return result


def file_record(path: Path) -> dict:
    stat = path.stat()
    value = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    # Large inputs were hashed when acquired; changing their metadata invalidates
    # a checkpoint. Final delivery performs the full scientific checksum gate.
    if stat.st_size <= 8 * 1024 * 1024:
        value["sha256"] = sha256_file(path)
    return value


def fingerprint(stage: Stage, state: dict, root: Path | None = None) -> str:
    root = root or PROJECT_ROOT
    records = {p: file_record(root / p) if (root / p).is_file() else None for p in stage.inputs}
    parents = {d: state.get("stages", {}).get(d, {}).get("outputs", {}) for d in stage.dependencies}
    return hashlib.sha256(json.dumps({"inputs": records, "parents": parents}, sort_keys=True).encode()).hexdigest()


def checkpoint_valid(stage: Stage, record: dict, expected: str, root: Path | None = None) -> bool:
    root = root or PROJECT_ROOT
    if record.get("status") != "complete" or record.get("fingerprint") != expected:
        return False
    saved = record.get("outputs", {})
    return all((root / p).is_file() and saved.get(p) == file_record(root / p) for p in stage.outputs)


def process_identity(pid: int) -> dict | None:
    try:
        p = psutil.Process(pid)
        if p.status() == psutil.STATUS_ZOMBIE:
            return None
        return {"pid": pid, "created": p.create_time()}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def is_live(identity: dict | None) -> bool:
    return bool(identity and process_identity(int(identity["pid"])) == identity)


def is_paused(identity: dict | None) -> bool:
    """An OS-paused child is alive, but is not doing scientific computation.

    Check its birth time before its state so a recycled PID cannot manufacture
    a pause. Reporting this does not signal a process or authorise resumption.
    """
    if not is_live(identity):
        return False
    try:
        return psutil.Process(identity["pid"]).status() == psutil.STATUS_STOPPED
    except psutil.Error:
        return False


def read_state(path: Path | None = None) -> dict:
    path = path or STATE
    return json.loads(path.read_text()) if path.exists() else {"schema_version": 1, "stages": {}}


def stop_group(identity: dict | None) -> None:
    """Only signal the validated process group created for this stage."""
    if not is_live(identity):
        return
    pid = int(identity["pid"])
    if os.getpgid(pid) != pid:
        raise Track1Error("Refusing to stop a process outside the owned stage group")
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 20
    while is_live(identity) and time.monotonic() < deadline:
        time.sleep(0.2)
    if is_live(identity):
        os.killpg(pid, signal.SIGKILL)


def request_stop() -> str:
    """Stop the live supervisor, or recover its owned children after a crash.

    A state file or reused PID alone does not establish ownership. Recovery
    requires the project lock plus each child's recorded process start time.
    """
    state = read_state()
    if is_live(state.get("supervisor")):
        os.kill(state["supervisor"]["pid"], signal.SIGTERM)
        return "Clean stop requested; checkpoints will be retained."
    ensure_private_dir(STATE_DIR)
    with (STATE_DIR / "run.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise Track1Error("Supervisor ownership changed; recheck status before stopping") from exc
        state = read_state()
        if is_live(state.get("supervisor")):
            raise Track1Error("Supervisor ownership changed; recheck status before stopping")
        count = 0
        for record in state.get("stages", {}).values():
            if record.get("status") == "running" and is_live(record.get("child")):
                stop_group(record["child"])
                record.update({"status": "stopped", "error_category": "supervisor_interrupted"})
                count += 1
        if count:
            state.update({"status": "stopped", "finished_at": utc_now()})
            atomic_write_json(STATE, state)
            return f"Stopped {count} verified orphaned stage group(s); checkpoints retained."
    return "No live supervisor or verified stage child found."


def _memory_usage(identities: list[dict | None]) -> int:
    processes = {}
    for identity in identities:
        if not is_live(identity):
            continue
        try:
            parent = psutil.Process(identity["pid"])
            processes.update({p.pid: p for p in [parent, *parent.children(recursive=True)]})
        except psutil.Error:
            continue
    total = 0
    for process in processes.values():
        try:
            total += process.memory_info().rss
        except psutil.Error:
            pass
    return total


def run(tracks: str = "both", only: tuple[str, ...] = ()) -> int:
    ensure_private_dir(STATE_DIR)
    ensure_private_dir(PROJECT_ROOT / "logs")
    cfg = load_jsonish(EXECUTION)
    from .preflight import limits_valid
    if not limits_valid(cfg.get("limits", {})):
        raise Track1Error("Execution limits exceed the approved contract or have invalid units")
    lock = (STATE_DIR / "run.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise Track1Error("A supervisor already owns this project") from exc
    state = read_state()
    state.update({"supervisor": process_identity(os.getpid()), "status": "running", "tracks": tracks})
    cpus = sorted(os.sched_getaffinity(0))[:int(cfg["limits"]["cpus"])]
    os.sched_setaffinity(0, cpus)
    stopped = False

    def request_stop(signum, frame):
        nonlocal stopped
        stopped = True
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, request_stop)
    available = {s.name: s for s in stages(tracks)}
    selected = set(only) if only else set(available)
    if selected - set(available):
        raise Track1Error("Unknown requested stage")
    while True:
        expanded = selected | {d for n in selected for d in available[n].dependencies}
        if expanded == selected:
            break
        selected = expanded
    state["selected_stages"] = sorted(selected)
    failed = set()
    for stage in available.values():
        if stage.name not in selected or stopped:
            continue
        if set(stage.dependencies) & failed:
            failed.add(stage.name)
            state["stages"][stage.name] = {"status": "blocked_dependency"}
            continue
        expected = fingerprint(stage, state)
        previous = state["stages"].get(stage.name, {})
        if checkpoint_valid(stage, previous, expected):
            continue
        record = {"status": "running", "fingerprint": expected, "started_at": utc_now(),
                  "attempts": 0, "log": f"logs/stage_{stage.name}.log"}
        result_path = STATE_DIR / f"{stage.name}.result.json"
        # A child may survive an interrupted supervisor. Adopt its real PID,
        # rather than launching another copy merely because a lock is stale.
        adopted = previous.get("child") if previous.get("status") == "running" else None
        child = None
        try:
            if is_live(adopted):
                record.update(previous)
            else:
                require_space(stage.estimate_bytes)
            attempts = int(cfg["supervisor"]["transient_attempts"])
            for attempt in range(attempts):
                if stopped:
                    break
                if is_live(adopted):
                    record["child"] = adopted
                    adopted = None
                else:
                    if result_path.exists():
                        result_path.unlink()
                    record["attempts"] += 1
                    with (PROJECT_ROOT / record["log"]).open("a") as log:
                        child = subprocess.Popen([sys.executable, "-m", "mva_runner.tasks", stage.name,
                                                  "--receipt", str(result_path)], cwd=PROJECT_ROOT,
                                                 stdout=log, stderr=log, start_new_session=True)
                    record["child"] = process_identity(child.pid)
                state["stages"][stage.name] = record
                atomic_write_json(STATE, state)
                while is_live(record.get("child")):
                    if stopped:
                        stop_group(record["child"])
                        break
                    require_space()
                    model_state = STATE_DIR / "model_process.json"
                    model_identity = read_state(model_state).get("process") if model_state.exists() else None
                    rss = _memory_usage([record["child"], model_identity])
                    if rss > int(cfg["limits"]["memory_gib"]) * 2**30:
                        raise Track1Error("Memory limit reached")
                    state.update({"heartbeat": utc_now(), "memory_bytes": rss})
                    atomic_write_json(STATE, state)
                    time.sleep(float(cfg["supervisor"]["heartbeat_seconds"]))
                if child is not None:
                    child.wait()
                result = read_state(result_path) if result_path.exists() else {"status": "interrupted"}
                if result.get("status") == "complete":
                    if not all((PROJECT_ROOT / p).is_file() for p in stage.outputs):
                        raise Track1Error("Stage completed without its required artifacts")
                    record.update({"status": "complete", "completed_at": utc_now(),
                                   "outputs": {p: file_record(PROJECT_ROOT / p) for p in stage.outputs}})
                    break
                if result.get("retryable") and attempt + 1 < attempts:
                    time.sleep(min(300, float(cfg["supervisor"]["retry_seconds"]) * 2**attempt))
                    continue
                record.update({"status": "stopped" if stopped else "failed",
                               "error_category": result.get("error_category", "interrupted")})
                failed.add(stage.name)
                break
        except (BudgetExceeded, Track1Error, OSError) as exc:
            stop_group(record.get("child"))
            record.update({"status": "blocked", "error_category": type(exc).__name__})
            if isinstance(exc, BudgetExceeded):
                record["space_request"] = str(exc)
            failed.add(stage.name)
        state["stages"][stage.name] = record
        state["heartbeat"] = utc_now()
        atomic_write_json(STATE, state)
    state["status"] = "stopped" if stopped else ("blocked" if failed else "complete")
    state["finished_at"] = utc_now()
    atomic_write_json(STATE, state)
    lock.close()
    return 0 if state["status"] == "complete" else 2
