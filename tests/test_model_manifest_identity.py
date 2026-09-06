"""Model metadata uses invented hashes and never starts inference or downloads."""
import json

import pytest

from mva_runner import local
from mva_runner.supervisor import file_record


def test_verified_unchanged_installation_preserves_bytes_and_mtime(tmp_path, monkeypatch):
    path = tmp_path / 'install_manifest.json'
    monkeypatch.setattr(local, 'MANIFEST', path)
    monkeypatch.setattr(local, 'utc_now', lambda: '2026-09-05T01:00:00+00:00')
    model, runtime = {'sha256': 'a' * 64}, {'binary_sha256': 'b' * 64}
    local._record_install_manifest(model, runtime)
    previous = file_record(path)
    monkeypatch.setattr(local, 'utc_now', lambda: '2026-09-06T01:00:00+00:00')
    local._record_install_manifest(model, runtime)
    assert file_record(path) == previous
    assert json.loads(path.read_text())['created_at'] == '2026-09-05T01:00:00+00:00'


@pytest.mark.parametrize('changed_component', ['model', 'runtime'])
def test_changed_verified_installation_gets_a_new_identity(tmp_path, monkeypatch, changed_component):
    path = tmp_path / 'install_manifest.json'
    monkeypatch.setattr(local, 'MANIFEST', path)
    monkeypatch.setattr(local, 'utc_now', lambda: '2026-09-05T01:00:00+00:00')
    model, runtime = {'sha256': 'a' * 64}, {'binary_sha256': 'b' * 64}
    local._record_install_manifest(model, runtime)
    previous = file_record(path)
    (model if changed_component == 'model' else runtime)['revision'] = 'synthetic-new-revision'
    monkeypatch.setattr(local, 'utc_now', lambda: '2026-09-06T01:00:00+00:00')
    local._record_install_manifest(model, runtime)
    assert file_record(path)['sha256'] != previous['sha256']
    assert json.loads(path.read_text())['created_at'] == '2026-09-06T01:00:00+00:00'


def test_missing_installation_timestamp_is_recorded_after_verification(tmp_path, monkeypatch):
    path = tmp_path / 'install_manifest.json'
    model, runtime = {'sha256': 'a' * 64}, {'binary_sha256': 'b' * 64}
    path.write_text(json.dumps({'model': model, 'runtime': runtime}))
    monkeypatch.setattr(local, 'MANIFEST', path)
    monkeypatch.setattr(local, 'utc_now', lambda: '2026-09-06T01:00:00+00:00')
    local._record_install_manifest(model, runtime)
    assert json.loads(path.read_text())['created_at'] == '2026-09-06T01:00:00+00:00'
