"""Bounded Codex review recovery uses only invented candidate records."""
import copy
import json

import pytest

from mva_runner import review
from mva_runner.codex_review import InterpretationError, ReviewRequired


@pytest.fixture
def payload(tmp_path, monkeypatch):
    monkeypatch.setattr(review, 'PROJECT_ROOT', tmp_path)
    return {'candidates': [
        {'candidate_id': 'synthetic-a', 'gene': 'SYNTH_A', 'phase_status': 'unresolved'},
        {'candidate_id': 'synthetic-b', 'gene': 'SYNTH_B', 'phase_status': 'unresolved'}],
        'phenotype': {'notes': 'synthetic only'}}


def answer(gene='SYNTH_A'):
    return {'selections': [{'candidate_id': 'synthetic-a', 'finding_type': 'primary',
        'rationale': 'Synthetic hypothesis only', 'uncertainty': 'Phase is unresolved',
        'evidence': [{'field': 'gene', 'value': gene}, {'field': 'phase_status', 'value': 'unresolved'}]}]}


def test_cross_candidate_evidence_requires_another_review(payload, monkeypatch, tmp_path):
    original, requests = copy.deepcopy(payload), []
    rejected = answer('SYNTH_B')
    def respond(system, user, schema, purpose):
        request = json.loads(user)
        requests.append(request)
        assert request['candidates'] == original['candidates']
        if len(requests) == 1:
            return rejected
        assert request['validation_feedback']['previous_response'] == rejected
        return answer()
    monkeypatch.setattr(review, 'review_evidence', respond)
    accepted, attempts = review.review_finalist_selections('synthetic', payload, {})
    assert accepted == answer() and payload == original and rejected == answer('SYNTH_B')
    assert [r['status'] for r in attempts] == ['rejected', 'accepted']
    receipt = tmp_path / 'work/private/finalist_review_attempts.json'
    assert json.loads(receipt.read_text())['review_mode'] == 'codex_assisted'
    assert receipt.stat().st_mode & 0o777 == 0o600


def test_three_invalid_reviews_fail_closed(payload, monkeypatch):
    requests = []
    def respond(system, user, schema, purpose):
        requests.append(user)
        return answer('SYNTH_B')
    monkeypatch.setattr(review, 'review_evidence', respond)
    with pytest.raises(InterpretationError, match='three review attempts'):
        review.review_finalist_selections('synthetic', payload, {})
    assert len(requests) == len(set(requests)) == 3


def test_waiting_is_not_retried_as_bad_evidence(payload, monkeypatch):
    calls = []
    def pending(*args):
        calls.append(True)
        raise ReviewRequired('Synthetic review needed')
    monkeypatch.setattr(review, 'review_evidence', pending)
    with pytest.raises(ReviewRequired):
        review.review_finalist_selections('synthetic', payload, {})
    assert len(calls) == 1
