"""Synthetic recovery and budget contracts; never load challenge data."""
import json
from pathlib import Path

import pytest

from mva_runner import storage
from mva_runner.supervisor import Stage, checkpoint_valid, file_record, fingerprint, is_live
from mva_track1.common import load_jsonish


def test_budget_includes_reserve_and_refuses_unapproved_growth(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"root":str(tmp_path),"allocated_bytes":1000}))
    monkeypatch.setattr(storage, "allocated_bytes", lambda root: 1300)
    config = {"limits":{"additional_disk_bytes":500,"disk_reserve_bytes":50}}
    assert storage.require_space(150, root=tmp_path, baseline_path=baseline, config=config)["remaining_bytes"] == 200
    with pytest.raises(storage.BudgetExceeded):
        storage.require_space(151, root=tmp_path, baseline_path=baseline, config=config)


def test_baseline_cannot_silently_increase(tmp_path, monkeypatch):
    baseline = tmp_path / "baseline.json"
    original = {"root":str(tmp_path),"allocated_bytes":1000}
    baseline.write_text(json.dumps(original))
    monkeypatch.setattr(storage, "allocated_bytes", lambda root: 9000)
    assert storage.establish_baseline(tmp_path, baseline) == original


def test_changed_output_and_upstream_invalidate_checkpoint(tmp_path):
    (tmp_path / "input").write_text("synthetic input")
    output = tmp_path / "output"
    output.write_text("synthetic result")
    stage = Stage("test", ("parent",), ("input",), ("output",))
    state = {"stages":{"parent":{"outputs":{"previous":"one"}}}}
    first = fingerprint(stage, state, tmp_path)
    record = {"status":"complete","fingerprint":first,"outputs":{"output":file_record(output)}}
    assert checkpoint_valid(stage, record, first, tmp_path)
    state["stages"]["parent"]["outputs"]["previous"] = "two"
    assert not checkpoint_valid(stage, record, fingerprint(stage, state, tmp_path), tmp_path)
    output.write_text("corrupted result")
    assert not checkpoint_valid(stage, record, first, tmp_path)


def test_missing_pid_is_not_a_live_job():
    assert not is_live({"pid":2147483647,"created":0})


def test_commented_yaml_and_old_json_are_both_supported(tmp_path):
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text("# Units are bytes\nlimit: 250000000000\n")
    json_path = tmp_path / "config.json"
    json_path.write_text('{"limit":250000000000}')
    assert load_jsonish(yaml_path) == load_jsonish(json_path)
