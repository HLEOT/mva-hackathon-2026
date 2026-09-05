"""Synthetic status identities only; these tests never signal real processes."""
import json

import pytest

from mva_runner import cli, supervisor


@pytest.mark.parametrize("status, expected", [(supervisor.psutil.STATUS_STOPPED, True),
                                              (supervisor.psutil.STATUS_SLEEPING, False)])
def test_pause_status_distinguishes_stopped_from_idle(monkeypatch, status, expected):
    monkeypatch.setattr(supervisor, "is_live", lambda identity: True)
    class Process:
        def status(self):
            return status
    monkeypatch.setattr(supervisor.psutil, "Process", lambda pid: Process())
    assert supervisor.is_paused({"pid": 123, "created": 1.0}) is expected


def test_stale_identity_is_not_reported_as_paused(monkeypatch):
    monkeypatch.setattr(supervisor, "is_live", lambda identity: False)
    monkeypatch.setattr(supervisor.psutil, "Process", lambda pid: pytest.fail("Stale process was inspected"))
    assert not supervisor.is_paused({"pid": 123, "created": 1.0})


def test_disappearing_process_does_not_break_status(monkeypatch):
    monkeypatch.setattr(supervisor, "is_live", lambda identity: True)
    def missing(pid):
        raise supervisor.psutil.NoSuchProcess(pid)
    monkeypatch.setattr(supervisor.psutil, "Process", missing)
    assert not supervisor.is_paused({"pid": 123, "created": 1.0})


def test_cli_exposes_pause_without_disclosing_raw_worker_records(monkeypatch, capsys):
    identity = {"pid": 123, "created": 1.0}
    state = {"status": "running", "supervisor": identity, "stages": {
        "validate_reads": {"status": "running", "child": identity, "private_diagnostic": "synthetic hidden value"},
        "model": {"status": "complete"}}}
    monkeypatch.setattr(cli, "load_jsonish", lambda path: {})
    monkeypatch.setattr(supervisor, "read_state", lambda: state)
    monkeypatch.setattr(supervisor, "is_live", lambda candidate: candidate == identity)
    monkeypatch.setattr(supervisor, "is_paused", lambda candidate: candidate == identity)
    monkeypatch.setattr(cli, "snapshot", lambda: {"remaining_bytes": 20_000_000_000})
    assert cli.main(["status", "--json"]) == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["supervisor_live"] is True
    assert report["paused_stages"] == ["validate_reads"]
    assert report["stages"]["validate_reads"]["child_paused"] is True
    assert report["stages"]["model"]["child_paused"] is False
    assert "synthetic hidden value" not in output
    assert '"pid"' not in output
