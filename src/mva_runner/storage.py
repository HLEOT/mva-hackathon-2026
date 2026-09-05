"""Account for physical storage, including Conda hard links and private caches.

GNU du counts each inode once within a project, avoiding a double charge for
hard-linked package files while counting independent download copies. Never
automatically reset the baseline: that would reset the user's allowance.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, utc_now

BASELINE = PROJECT_ROOT / "work/private/runner/storage_baseline.json"
EXECUTION = PROJECT_ROOT / "config/execution.yaml"


class BudgetExceeded(Track1Error):
    """A stage needs more space than the user has authorised."""


def allocated_bytes(root: Path = PROJECT_ROOT) -> int:
    result = subprocess.run(["du", "-s", "-B1", str(root)], check=True,
                            text=True, capture_output=True)
    return int(result.stdout.split()[0])


def establish_baseline(root: Path = PROJECT_ROOT, path: Path = BASELINE) -> dict:
    """Create once, or validate the existing baseline without increasing it."""
    if path.exists():
        value = json.loads(path.read_text())
        if value.get("root") != str(root.resolve()) or value.get("allocated_bytes", -1) < 0:
            raise Track1Error("Invalid storage baseline; manual investigation required")
        return value
    value = {"schema_version": 1, "root": str(root.resolve()),
             "allocated_bytes": allocated_bytes(root), "recorded_at": utc_now()}
    atomic_write_json(path, value)
    return value


def snapshot(root: Path = PROJECT_ROOT, baseline_path: Path = BASELINE,
             config: dict | None = None) -> dict:
    if not baseline_path.exists():
        raise Track1Error("Storage baseline absent; initialise it before downloading")
    baseline = json.loads(baseline_path.read_text())
    if baseline.get("root") != str(root.resolve()):
        raise Track1Error("Storage baseline belongs to a different checkout")
    limits = (config or load_jsonish(EXECUTION))["limits"]
    usage = allocated_bytes(root)
    delta = max(0, usage - int(baseline["allocated_bytes"]))
    allowance = int(limits["additional_disk_bytes"])
    return {"baseline_bytes": baseline["allocated_bytes"], "allocated_bytes": usage,
            "additional_bytes": delta, "allowance_bytes": allowance,
            "remaining_bytes": allowance - delta,
            "filesystem_free_bytes": shutil.disk_usage(root).free,
            "reserve_bytes": int(limits["disk_reserve_bytes"])}


def require_space(estimate_bytes: int = 0, **kwargs) -> dict:
    """Reserve estimated peak stage growth plus a buffer for in-flight writes."""
    state = snapshot(**kwargs)
    required = max(0, estimate_bytes) + state["reserve_bytes"]
    available = min(state["remaining_bytes"], state["filesystem_free_bytes"])
    if available < required:
        raise BudgetExceeded(
            f"Additional space approval required: need {required} bytes including "
            f"reserve, available {available} bytes within current limits")
    return state
