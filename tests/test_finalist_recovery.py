"""Bounded local review recovery against invented candidate records only."""
import copy
import json
import urllib.error

import pytest

from mva_runner import review
from mva_runner.local import InterpretationError


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "PROJECT_ROOT", tmp_path)
    return {"candidates": [
        {"candidate_id": "synthetic-a", "gene": "SYNTH_A", "phase_status": "unresolved"},
        {"candidate_id": "synthetic-b", "gene": "SYNTH_B", "phase_status": "unresolved"},
    ], "phenotype": {"notes": "synthetic only"}}


def answer(gene="SYNTH_A"):
    return {"selections": [{"candidate_id": "synthetic-a", "finding_type": "primary",
        "rationale": "Synthetic hypothesis only", "uncertainty": "Phase is unresolved",
        "evidence": [{"field": "gene", "value": gene}, {"field": "phase_status", "value": "unresolved"}]}]}


def test_cross_candidate_evidence_requires_new_validated_local_answer(payload, monkeypatch, tmp_path):
    original = copy.deepcopy(payload)
    rejected = answer("SYNTH_B")
    requests = []

    def infer(system, user, schema, purpose):
        request = json.loads(user)
        requests.append(request)
        assert request["candidates"] == original["candidates"]
        if len(requests) == 1:
            assert "validation_feedback" not in request
            return rejected
        assert request["validation_feedback"]["previous_response"] == rejected
        assert "own candidate_id" in request["validation_feedback"]["instruction"]
        return answer()

    monkeypatch.setattr(review, "infer", infer)
    accepted, attempts = review.infer_finalist_selections("synthetic", payload, {})
    assert accepted == answer()
    assert [item["status"] for item in attempts] == ["rejected", "accepted"]
    assert rejected == answer("SYNTH_B")  # Never silently rewrite copied evidence.
    assert payload == original
    receipt = tmp_path / "work/private/finalist_review_attempts.json"
    assert json.loads(receipt.read_text())["completed"] is True
    assert receipt.stat().st_mode & 0o777 == 0o600


def test_repeated_invalid_answers_stop_after_three_distinct_requests(payload, monkeypatch, tmp_path):
    requests = []

    def infer(system, user, schema, purpose):
        requests.append(user)
        return answer("SYNTH_B")

    monkeypatch.setattr(review, "infer", infer)
    with pytest.raises(InterpretationError, match="three local attempts"):
        review.infer_finalist_selections("synthetic", payload, {})
    assert len(requests) == len(set(requests)) == 3
    receipt = json.loads((tmp_path / "work/private/finalist_review_attempts.json").read_text())
    assert receipt["completed"] is False
    assert [item["status"] for item in receipt["attempts"]] == ["rejected"] * 3


def test_schema_rejection_is_retried_without_inventing_a_previous_answer(payload, monkeypatch):
    calls = []

    def infer(system, user, schema, purpose):
        calls.append(json.loads(user))
        if len(calls) == 1:
            raise InterpretationError("Local output failed schema validation")
        assert calls[-1]["validation_feedback"]["previous_response"] is None
        return answer()

    monkeypatch.setattr(review, "infer", infer)
    accepted, attempts = review.infer_finalist_selections("synthetic", payload, {})
    assert accepted == answer()
    assert len(attempts) == 2


def test_transport_failure_is_left_to_supervisor_not_interpretation_retry(payload, monkeypatch):
    calls = []

    def infer(*args):
        calls.append(True)
        raise urllib.error.URLError("synthetic unavailable loopback")

    monkeypatch.setattr(review, "infer", infer)
    with pytest.raises(urllib.error.URLError):
        review.infer_finalist_selections("synthetic", payload, {})
    assert len(calls) == 1


def test_valid_first_answer_is_not_regenerated(payload, monkeypatch):
    calls = []

    def infer(*args):
        calls.append(True)
        return answer()

    monkeypatch.setattr(review, "infer", infer)
    accepted, attempts = review.infer_finalist_selections("synthetic", payload, {})
    assert accepted == answer()
    assert attempts == [{"attempt": 1, "status": "accepted"}]
    assert len(calls) == 1
