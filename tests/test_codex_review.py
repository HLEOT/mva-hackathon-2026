"""No patient data or actual model calls: synthetic file-backed review contracts."""
import json

import pytest

from mva_runner import codex_review as review
from mva_runner import delivery, supervisor
from mva_track1.common import atomic_write_json, Track1Error

SCHEMA = {'type': 'object', 'properties': {'valid': {'type': 'boolean'}},
          'required': ['valid'], 'additionalProperties': False}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(review, 'PROJECT_ROOT', tmp_path)
    return tmp_path


def authorize(project):
    atomic_write_json(project / 'config/ai_usage.local.yaml', {
        'private_codex_review_authorized': True, 'provider_terms_confirmed': True,
        'hosted_plan': 'synthetic-only', 'hosted_data_setting': 'synthetic-only'})


def request(project):
    authorize(project)
    with pytest.raises(review.ReviewRequired):
        review.review_evidence('Synthetic instructions', '{"invented":"evidence"}', SCHEMA, 'synthetic')
    pending = review.pending_reviews()[0]
    path = project / pending['directory'] / (pending['request_sha256'] + '.response.json')
    return path, {'request_sha256': pending['request_sha256'], 'reviewed_by': 'Codex',
        'review_mode': 'codex_assisted', 'reviewed_at': '2026-09-06T00:00:00+00:00', 'answer': {'valid': True}}


def test_unconfirmed_terms_do_not_create_evidence_requests(project):
    with pytest.raises(review.ReviewRequired, match='terms'):
        review.review_evidence('synthetic', '{}', SCHEMA, 'synthetic')
    assert not (project / 'work/private/reviews').exists()


def test_pending_response_resume_and_receipt(project):
    path, response = request(project)
    assert 'invented' not in json.dumps(review.pending_reviews())
    atomic_write_json(path, response)
    assert review.review_evidence('Synthetic instructions', '{"invented":"evidence"}', SCHEMA, 'synthetic') == {'valid': True}
    receipt = review.review_receipt('synthetic')
    assert not review.pending_reviews() and path.stat().st_mode & 0o777 == 0o600
    response['answer']['valid'] = False
    atomic_write_json(path, response)
    with pytest.raises(review.InterpretationError, match='changed'):
        review.verify_receipt(receipt)


@pytest.mark.parametrize('key,value', [('request_sha256', '0'*64), ('reviewed_by', 'legacy-local'),
    ('review_mode', 'automated_local'), ('answer', {'valid': 'yes'}), ('reviewed_at', '2026-09-06')])
def test_stale_legacy_or_invalid_response_is_rejected(project, key, value):
    path, response = request(project)
    response[key] = value
    atomic_write_json(path, response)
    with pytest.raises(review.InterpretationError):
        review.review_evidence('Synthetic instructions', '{"invented":"evidence"}', SCHEMA, 'synthetic')


def test_changed_evidence_requires_a_new_response(project):
    path, response = request(project)
    atomic_write_json(path, response)
    with pytest.raises(review.ReviewRequired):
        review.review_evidence('Synthetic instructions', '{"invented":"different"}', SCHEMA, 'synthetic')


def test_graph_has_no_model_and_invalidates_changed_review(project, monkeypatch):
    monkeypatch.setattr(supervisor, 'PROJECT_ROOT', project)
    before = {s.name: s for s in supervisor.stages()}
    assert 'model' not in before and all('model' not in s.dependencies for s in before.values())
    path = project / 'work/private/reviews/phenotype/synthetic.response.json'
    atomic_write_json(path, {'synthetic': True})
    after = {s.name: s for s in supervisor.stages()}
    assert before['phenotype'].inputs != after['phenotype'].inputs
    assert before['validate_reads'].inputs == after['validate_reads'].inputs


def test_delivery_refuses_legacy_reviews_before_relabelling(project, monkeypatch):
    authorize(project)
    monkeypatch.setattr(delivery, 'PROJECT_ROOT', project)
    atomic_write_json(project / 'work/private/phenotype_review.json', {'review_mode': 'automated_local'})
    with pytest.raises(review.ReviewRequired, match='predates'):
        delivery.assert_codex_reviews()


def test_purpose_cannot_escape_private_review_tree(project):
    authorize(project)
    with pytest.raises(Track1Error):
        review.review_evidence('synthetic', '{}', SCHEMA, '../escape')
