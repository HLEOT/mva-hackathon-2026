"""Retain the exact measurements behind each automated read reassessment.

A second phasing/validation pass may replace the working table after exclusion
or reordering. Content-addressed tables and linked decisions keep that earlier
evidence auditable without changing its biological interpretation.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import re

from mva_track1.artifacts import READ_VALIDATION_FIELDS, PAIR_SUPPORT_VALUES, PHASE_STATUS_VALUES, validate_read_validation
from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, atomic_write_text, ensure_private_dir, sha256_file


def _rows(path: Path) -> list[dict]:
    reader = csv.DictReader(io.StringIO(path.read_bytes().decode('utf-8'), newline=''), delimiter='\t')
    rows = list(reader)
    if reader.fieldnames != READ_VALIDATION_FIELDS or not 1 <= len(rows) <= 10:
        raise Track1Error('Archived read measurements have an invalid schema or row count')
    ids = [row.get('candidate_id') for row in rows]
    if not all(ids) or len(set(ids)) != len(ids) or any(None in row or None in row.values() for row in rows):
        raise Track1Error('Archived read measurements have incomplete or duplicate rows')
    if any(row['pair_support'] not in PAIR_SUPPORT_VALUES or row['phase_status'] not in PHASE_STATUS_VALUES for row in rows):
        raise Track1Error('Archived read measurements have invalid support or phase categories')
    return rows


def _store(raw: bytes, suffix: str) -> Path:
    directory = PROJECT_ROOT / 'work/private/read_evidence'
    if directory.is_symlink() or not directory.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise Track1Error('Read-evidence archive directory is unsafe')
    ensure_private_dir(directory)
    path = directory / (hashlib.sha256(raw).hexdigest() + suffix)
    if path.is_symlink() or not path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise Track1Error('Read-evidence archive must stay inside the project')
    if path.exists():
        if path.read_bytes() != raw:
            raise Track1Error('An existing immutable read-evidence archive differs')
    else:
        # Decode bytes directly: read_text would normalise CSV CRLF line endings
        # and silently change the checksum of the evidence being preserved.
        atomic_write_text(path, raw.decode('utf-8'))
    if sha256_file(path) != hashlib.sha256(raw).hexdigest():
        raise Track1Error('Read-evidence archive failed its byte-integrity check')
    return path


def _reference(name: str, suffix: str) -> Path:
    if not isinstance(name, str) or not re.fullmatch(r'work/private/read_evidence/[0-9a-f]{64}' + re.escape(suffix), name):
        raise Track1Error('Read-evidence archive reference is invalid')
    path = PROJECT_ROOT / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise Track1Error('Referenced read-evidence archive is unavailable or unsafe')
    if path.stat().st_size > 8 * 1024 * 1024 or sha256_file(path) != path.name[:64]:
        raise Track1Error('Referenced read-evidence archive checksum differs')
    return path


def verify_reassessment(*, check_current: bool = True) -> dict:
    """Check the decision trail and final coverage without exposing evidence text."""
    from .review import reviewed_finalists
    decision_path = PROJECT_ROOT / 'work/private/read_reassessment.json'
    if decision_path.is_symlink() or not decision_path.is_file() or not decision_path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
        raise Track1Error('Read reassessment is missing or unsafe')
    current = decision_path
    paths = {decision_path}
    seen, latest, decision_count = set(), None, 0
    while current is not None:
        if current in seen or len(seen) >= 50:
            raise Track1Error('Read-reassessment history is cyclic or unexpectedly long')
        seen.add(current)
        record = json.loads(current.read_bytes())
        if record.get('review_mode') != 'automated_deterministic':
            raise Track1Error('Read-reassessment review mode is invalid')
        evidence = _reference(record.get('read_evidence_path'), '.tsv')
        if record.get('read_evidence_sha256') != evidence.name[:64]:
            raise Track1Error('Read reassessment does not identify its archived measurements')
        rows = _rows(evidence)
        contradicted = lambda row: row['pair_support'] == 'unsupported' or row['phase_status'].endswith('_cis')
        excluded = [row['candidate_id'] for row in rows if contradicted(row)]
        retained = sorted((row for row in rows if not contradicted(row)), key=lambda row: row['pair_support'] != 'supported')
        if [row['candidate_id'] for row in record.get('excluded', [])] != excluded or record.get('retained_ids') != [row['candidate_id'] for row in retained]:
            raise Track1Error('Read-reassessment decision differs from its measured-evidence policy')
        if latest is None:
            latest = record
        if record.get('original_decision_path'):
            original = _reference(record['original_decision_path'], '.reassessment.json')
            if any(record.get(key) != value for key, value in json.loads(original.read_bytes()).items()):
                raise Track1Error('Original read-reassessment decision was changed')
            paths.add(original)
        paths.update([current, evidence])
        decision_count += 1
        current = _reference(record['previous_decision_path'], '.reassessment.json') if record.get('previous_decision_path') else None
    candidates = PROJECT_ROOT / 'results/private/candidates_ranked.tsv'
    finalists = PROJECT_ROOT / 'config/finalists.local.tsv'
    measurements = PROJECT_ROOT / 'results/private/read_validation.tsv'
    if check_current:
        selected = reviewed_finalists(finalists, candidates)
        final_rows = validate_read_validation(measurements, finalists, candidates)
        if [row['candidate_id'] for row in selected] != latest['retained_ids'] or any(
                row['pair_support'] == 'unsupported' or row['phase_status'].endswith('_cis') for row in final_rows):
            raise Track1Error('Final shortlist is inconsistent with measured read reassessment')
    artifacts = {str(path.relative_to(PROJECT_ROOT)): {'size': path.stat().st_size, 'sha256': sha256_file(path)} for path in sorted(paths)}
    return {'archive_checksums_verified': True, 'decision_policy_verified': True,
            'current_finalist_coverage_verified': check_current, 'decision_count': decision_count,
            'retained_count': len(latest['retained_ids']), 'current_measurements_sha256': sha256_file(measurements) if check_current else None,
            'artifacts': artifacts}


def reassess_with_archive() -> bool:
    """Archive before reassessment, including the all-contradicted failure case."""
    from . import review
    decision_path = PROJECT_ROOT / 'work/private/read_reassessment.json'
    previous = None
    before_decision = None
    if decision_path.exists():
        # Never overwrite an older, unverifiable decision to hide an audit gap.
        # A new first pass may already have a different active shortlist; check
        # historical decisions against their own archived inputs at this point.
        verify_reassessment(check_current=False)
        before_decision = decision_path.read_bytes()
        previous = _store(before_decision, '.reassessment.json')
    evidence = PROJECT_ROOT / 'results/private/read_validation.tsv'
    validate_read_validation(evidence, PROJECT_ROOT / 'config/finalists.local.tsv', PROJECT_ROOT / 'results/private/candidates_ranked.tsv')
    archive = _store(evidence.read_bytes(), '.tsv')
    try:
        changed = review.reassess_reads()
    finally:
        if decision_path.is_file():
            raw = decision_path.read_bytes()
            decision = json.loads(raw)
            if raw != before_decision and decision.get('read_evidence_sha256') == archive.name[:64]:
                original = _store(raw, '.reassessment.json')
                decision.update({'read_evidence_path': str(archive.relative_to(PROJECT_ROOT)),
                                 'original_decision_path': str(original.relative_to(PROJECT_ROOT))})
                if previous is not None:
                    decision['previous_decision_path'] = str(previous.relative_to(PROJECT_ROOT))
                atomic_write_json(decision_path, decision)
    if not decision_path.is_file() or json.loads(decision_path.read_bytes()).get('read_evidence_path') != str(archive.relative_to(PROJECT_ROOT)):
        raise Track1Error('Read reassessment did not retain its exact input evidence')
    return changed


def validate_reads() -> None:
    """Keep the existing read policy, with durable evidence across both passes."""
    from .scientific import workflow
    workflow('validate_finalists')
    if reassess_with_archive():
        workflow('validate_finalists')
    verify_reassessment()
