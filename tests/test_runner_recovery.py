"""Recovery uses synthetic subprocesses and a temporary project, never patient data."""
import errno
import fcntl
import hashlib
import json
import subprocess
import sys
import urllib.error

import pytest

from mva_runner import supervisor
from mva_runner.tasks import retryable_failure
from mva_track1.common import Track1Error


@pytest.fixture
def isolated_runner(tmp_path, monkeypatch):
    state_dir = tmp_path / "work/private/runner"
    state_dir.mkdir(parents=True)
    monkeypatch.setattr(supervisor, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(supervisor, "STATE_DIR", state_dir)
    monkeypatch.setattr(supervisor, "STATE", state_dir / "state.json")
    monkeypatch.setattr(supervisor, "load_jsonish", lambda path: {
        "limits": {"cpus": 1, "memory_gib": 1},
        "supervisor": {"transient_attempts": 2, "heartbeat_seconds": 0.01, "retry_seconds": 0.01}})
    monkeypatch.setattr(supervisor, "require_space", lambda *args, **kwargs: {})
    monkeypatch.setattr(supervisor.os, "sched_setaffinity", lambda *args: None)
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    return tmp_path, state_dir


@pytest.mark.parametrize("status,expected", [(429, True), (500, True), (503, True),
                                             (400, False), (401, False), (403, False), (404, False)])
def test_http_retry_policy_does_not_repeat_authentication_errors(status, expected):
    error = urllib.error.HTTPError("https://example.test/public", status, "synthetic", {}, None)
    wrapper = Track1Error("Sanitised wrapper")
    wrapper.__cause__ = error
    assert retryable_failure(wrapper) is expected


def test_wrapped_network_error_and_urllib_reason_are_retryable():
    error = urllib.error.URLError(TimeoutError("synthetic timeout"))
    wrapper = Track1Error("Sanitised wrapper")
    wrapper.__cause__ = error
    assert retryable_failure(wrapper)
    assert retryable_failure(OSError(errno.ECONNRESET, "synthetic reset"))
    assert not retryable_failure(OSError(errno.ENOSPC, "synthetic disk full"))
    assert not retryable_failure(ValueError("synthetic schema error"))


def test_requests_transport_and_explicit_4xx_response():
    import requests
    assert retryable_failure(requests.exceptions.Timeout("synthetic timeout"))
    response = requests.Response()
    response.status_code = 403
    error = requests.exceptions.HTTPError(response=response)
    error.__cause__ = requests.exceptions.ConnectionError("earlier transport issue")
    assert not retryable_failure(error)


def test_cyclic_exception_chain_terminates():
    one, two = ValueError("one"), ValueError("two")
    one.__cause__, two.__cause__ = two, one
    assert not retryable_failure(one)


def test_stage_fingerprints_include_ordered_rules_without_cross_stage_churn(tmp_path):
    stages = {stage.name: stage for stage in supervisor.stages()}
    state = {"stages": {}}
    before = {name: supervisor.fingerprint(stage, state, tmp_path) for name, stage in stages.items()}
    changed = tmp_path / "workflow/rules/50_alignment.smk"
    changed.parent.mkdir(parents=True)
    changed.write_text("# synthetic alignment implementation change\n")
    after = {name: supervisor.fingerprint(stage, state, tmp_path) for name, stage in stages.items()}
    assert before["validate_reads"] != after["validate_reads"]
    assert before["prioritise"] == after["prioritise"]
    assert before["model"] == after["model"]
    assert "src/mva_track2/sources.py" in stages["public_evidence"].inputs
    assert "src/mva_runner/render.py" in stages["package"].inputs


def test_track1_subset_does_not_claim_to_package_track2():
    names = {stage.name for stage in supervisor.stages("track1")}
    assert "validate_reads" in names
    assert names.isdisjoint({"package", "track2", "public_evidence"})
    assert "package" in {stage.name for stage in supervisor.stages("both")}


def test_duplicate_supervisor_cannot_acquire_project_lock(isolated_runner):
    _, state_dir = isolated_runner
    with (state_dir / "run.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(Track1Error, match="already owns"):
            supervisor.run()


def test_resume_adopts_actual_live_child_without_duplicate_launch(isolated_runner, monkeypatch):
    root, state_dir = isolated_runner
    stage = supervisor.Stage("synthetic", (), (), ("result.txt",))
    monkeypatch.setattr(supervisor, "stages", lambda tracks: [stage])
    receipt = state_dir / "synthetic.result.json"
    # This child has its own group, just like a real worker. Only synthetic
    # status and result files are written inside pytest's temporary project.
    code = ("import pathlib,time; time.sleep(0.2); "
            "pathlib.Path('result.txt').write_text('synthetic result'); "
            f"pathlib.Path({str(receipt)!r}).write_text('{{\"status\":\"complete\"}}')")
    child = subprocess.Popen([sys.executable, "-c", code], cwd=root, start_new_session=True)
    try:
        identity = supervisor.process_identity(child.pid)
        assert supervisor.is_live(identity)
        state = {"stages": {"synthetic": {
            "status": "running", "child": identity, "attempts": 1,
            "fingerprint": supervisor.fingerprint(stage, {}, root), "log": "logs/synthetic.log"}}}
        supervisor.atomic_write_json(state_dir / "state.json", state)
        monkeypatch.setattr(supervisor.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("duplicate worker launched"))
        assert supervisor.run() == 0
        record = supervisor.read_state()["stages"]["synthetic"]
        assert record["status"] == "complete"
        assert record["attempts"] == 1
        assert supervisor.checkpoint_valid(stage, record, record["fingerprint"], root)
    finally:
        child.wait(timeout=10)


def test_stop_recovers_owned_child_when_supervisor_is_gone(isolated_runner):
    root, state_dir = isolated_runner
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             cwd=root, start_new_session=True)
    try:
        identity = supervisor.process_identity(child.pid)
        supervisor.atomic_write_json(state_dir / "state.json", {
            "status": "running", "supervisor": {"pid": 2147483647, "created": 0},
            "stages": {"synthetic": {"status": "running", "child": identity}}})
        assert "Stopped 1" in supervisor.request_stop()
        assert not supervisor.is_live(identity)
        assert supervisor.read_state()["status"] == "stopped"
    finally:
        child.wait(timeout=10)


def test_stop_rejects_reused_pid_without_signalling_it(isolated_runner, monkeypatch):
    _, state_dir = isolated_runner
    wrong_identity = supervisor.process_identity(supervisor.os.getpid())
    wrong_identity["created"] -= 1
    supervisor.atomic_write_json(state_dir / "state.json", {
        "stages": {"synthetic": {"status": "running", "child": wrong_identity}}})
    monkeypatch.setattr(supervisor.os, "killpg", lambda *args: pytest.fail("unowned group signalled"))
    assert "No live supervisor" in supervisor.request_stop()
