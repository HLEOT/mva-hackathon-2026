"""Invented read rows test history retention without reading real variants."""
import csv
import hashlib
import json

import pytest

from mva_runner import read_evidence, review, scientific, supervisor, tasks
from mva_track1 import artifacts
from mva_track1.common import Track1Error


def write_selected(root, identifiers):
    path = root / 'config/finalists.local.tsv'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, ['candidate_id', 'selected', 'final_rank', 'finding_type', 'review_reason'], delimiter='\t')
        writer.writeheader()
        for rank, identifier in enumerate(identifiers, 1):
            writer.writerow({'candidate_id': identifier, 'selected': 'YES', 'final_rank': rank,
                             'finding_type': 'primary', 'review_reason': 'Invented test evidence'})


def write_measured(root, observations):
    path = root / 'results/private/read_validation.tsv'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, artifacts.READ_VALIDATION_FIELDS, delimiter='\t')
        writer.writeheader()
        for identifier, support in observations:
            row = {field: '' for field in artifacts.READ_VALIDATION_FIELDS}
            row.update({'candidate_id': identifier, 'pair_support': support,
                        'phase_status': 'not_applicable_single_variant', 'phase_method': 'not_applicable',
                        'v1_support': support})
            writer.writerow(row)
    return path.read_bytes()


@pytest.fixture
def private_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(read_evidence, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(review, 'PROJECT_ROOT', tmp_path)
    # Candidate annotation/selection is covered elsewhere. Keep the actual
    # read-table and reassessment implementations, using invented selected IDs.
    def selected(path, candidates):
        with path.open(newline='') as stream:
            return sorted(csv.DictReader(stream, delimiter='\t'), key=lambda row: int(row['final_rank']))
    monkeypatch.setattr(review, 'reviewed_finalists', selected)
    monkeypatch.setattr(artifacts, 'reviewed_finalists', selected)
    (tmp_path / 'work/private').mkdir(parents=True)
    return tmp_path


def first_pass(root):
    observations = [('synthetic-supported', 'supported'), ('synthetic-excluded', 'unsupported'), ('synthetic-uncertain', 'ambiguous')]
    write_selected(root, [identifier for identifier, _ in observations])
    original = write_measured(root, observations)
    assert read_evidence.reassess_with_archive()
    write_measured(root, [observations[0], observations[2]])
    return original


def test_second_pass_keeps_exact_first_pass_bytes(private_fixture):
    root = private_fixture
    original = first_pass(root)
    decision = json.loads((root / 'work/private/read_reassessment.json').read_bytes())
    archive = root / decision['read_evidence_path']
    assert b'\r\n' in original and archive.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == decision['read_evidence_sha256']
    result = read_evidence.verify_reassessment()
    assert result['decision_policy_verified'] and result['current_finalist_coverage_verified']
    assert result['retained_count'] == 2 and result['decision_count'] == 1


def test_repeated_reassessment_retains_previous_exclusions(private_fixture):
    root = private_fixture
    first_pass(root)
    previous = (root / 'work/private/read_reassessment.json').read_bytes()
    assert not read_evidence.reassess_with_archive()
    decision = json.loads((root / 'work/private/read_reassessment.json').read_bytes())
    assert (root / decision['previous_decision_path']).read_bytes() == previous
    assert read_evidence.verify_reassessment()['decision_count'] == 2


def test_new_first_pass_checks_history_against_its_archived_inputs(private_fixture):
    root = private_fixture
    first_pass(root)
    write_selected(root, ['synthetic-new'])
    write_measured(root, [('synthetic-new', 'supported')])
    assert not read_evidence.reassess_with_archive()
    assert read_evidence.verify_reassessment()['decision_count'] == 2


def test_all_contradicted_failure_still_archives_its_evidence(private_fixture):
    root = private_fixture
    write_selected(root, ['synthetic-excluded'])
    original = write_measured(root, [('synthetic-excluded', 'unsupported')])
    with pytest.raises(Track1Error, match='All current finalists'):
        read_evidence.reassess_with_archive()
    decision = json.loads((root / 'work/private/read_reassessment.json').read_bytes())
    assert (root / decision['read_evidence_path']).read_bytes() == original
    assert read_evidence.verify_reassessment(check_current=False)['retained_count'] == 0
    with pytest.raises(Track1Error, match='inconsistent'):
        read_evidence.verify_reassessment()


@pytest.mark.parametrize('fault', ['archive_bytes', 'unsafe_reference', 'decision_policy'])
def test_tampering_never_passes_delivery_gate(private_fixture, fault):
    root = private_fixture
    first_pass(root)
    path = root / 'work/private/read_reassessment.json'
    decision = json.loads(path.read_bytes())
    if fault == 'archive_bytes':
        (root / decision['read_evidence_path']).write_bytes(b'damaged synthetic archive')
    elif fault == 'unsafe_reference':
        decision['read_evidence_path'] = '../outside.tsv'
    else:
        decision['retained_ids'].reverse()
    path.write_text(json.dumps(decision))
    with pytest.raises(Track1Error):
        read_evidence.verify_reassessment()


def test_unified_worker_archives_before_a_second_workflow_pass(private_fixture, monkeypatch):
    root = private_fixture
    observations = [('synthetic-supported', 'supported'), ('synthetic-excluded', 'unsupported')]
    write_selected(root, [identifier for identifier, _ in observations])
    calls = []
    def workflow(target):
        assert target == 'validate_finalists'
        calls.append(target)
        write_measured(root, observations if len(calls) == 1 else observations[:1])
    monkeypatch.setattr(scientific, 'workflow', workflow)
    tasks.execute('validate_reads')
    assert len(calls) == 2 and read_evidence.verify_reassessment()['retained_count'] == 1


def test_archive_code_is_scoped_to_read_and_delivery_checkpoints():
    stages = {stage.name: stage for stage in supervisor.stages('both')}
    source = 'src/mva_runner/read_evidence.py'
    assert source in stages['validate_reads'].inputs and source in stages['package'].inputs
    assert source not in stages['phenotype'].inputs and source not in stages['prioritise'].inputs
    assert 'work/private/read_reassessment.json' in stages['validate_reads'].outputs
