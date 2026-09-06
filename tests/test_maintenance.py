"""Destructive operations are exercised only against tiny invented resources."""
import json
import zipfile

import pytest

from mva_runner import maintenance as clean
from mva_track1 import resources
from mva_track1.common import Track1Error, atomic_write_json, sha256_file


@pytest.fixture
def installed(tmp_path, monkeypatch):
    monkeypatch.setattr(clean, 'PROJECT_ROOT', tmp_path)
    monkeypatch.setattr(resources, 'PROJECT_ROOT', tmp_path)
    root = tmp_path / 'exomiser'
    cli = root / 'exomiser-cli-15.1.0'
    downloads = root / 'downloads'
    downloads.mkdir(parents=True)
    entries = [('exomiser-cli-15.1.0-distribution.zip', 'exomiser-cli-15.1.0/exomiser-cli-15.1.0.jar', root),
               ('2602_hg38.zip', '2602_hg38/synthetic.db', cli / 'data'),
               ('2602_phenotype.zip', '2602_phenotype/synthetic.db', cli / 'data')]
    archives = []
    for name, member, destination in entries:
        archive = downloads / name
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr(member, b'synthetic resource')
        resources._extract_zip_safely(archive, destination)
        archives.append({'file': name, 'size': archive.stat().st_size,
                         'sha256': sha256_file(archive), 'url': 'https://example.test/' + name})
    atomic_write_json(root / 'install_manifest.json', {'version': '15.1.0', 'data_version': '2602', 'archives': archives})
    (root / '.complete').write_text('complete\n')
    config = tmp_path / 'config.json'
    atomic_write_json(config, {'annotation': {'exomiser_version': '15.1.0', 'exomiser_data_version': '2602', 'exomiser_dir': 'exomiser'}})
    return tmp_path, root, config


def test_compaction_preserves_verified_installed_files_and_original_provenance(installed):
    project, root, config = installed
    original = (root / 'install_manifest.json').read_bytes()
    before = {str(p): p.read_bytes() for p in (root / 'exomiser-cli-15.1.0').rglob('*') if p.is_file()}
    assert clean.compact_exomiser(root, apply=False)['archive_count'] == 3
    assert clean.compact_exomiser(root, apply=True)['removed_files'] == 3
    assert not list((root / 'downloads').glob('*.zip'))
    assert (root / 'install_manifest.json').read_bytes() == original
    assert before == {str(p): p.read_bytes() for p in (root / 'exomiser-cli-15.1.0').rglob('*') if p.is_file()}
    resources.verify_exomiser_install(config)
    assert clean.compact_exomiser(root, apply=True)['removed_files'] == 0
    assert list((project / 'work/private/runner/cleanup').glob('*.json'))


def test_corrupt_extracted_data_prevents_archive_deletion(installed):
    project, root, config = installed
    (root / 'exomiser-cli-15.1.0/data/2602_hg38/synthetic.db').write_bytes(b'X' * len(b'synthetic resource'))
    with pytest.raises(Track1Error, match='CRC'):
        clean.compact_exomiser(root, apply=True)
    assert len(list((root / 'downloads').glob('*.zip'))) == 3
    assert not (root / 'archive_compaction.json').exists()


def test_compacted_payload_keeps_full_checksum_gate(installed):
    project, root, config = installed
    clean.compact_exomiser(root, apply=True)
    (root / 'exomiser-cli-15.1.0/data/2602_hg38/synthetic.db').write_bytes(b'X' * len(b'synthetic resource'))
    resources.verify_exomiser_install(config, check_hashes=False)
    with pytest.raises(Track1Error, match='checksum'):
        resources.verify_exomiser_install(config)


def test_unexplained_missing_archive_still_fails(installed):
    project, root, config = installed
    (root / 'downloads/2602_hg38.zip').unlink()
    with pytest.raises(Track1Error, match='archive size'):
        resources.verify_exomiser_install(config)


def test_reinstall_archives_stale_compaction_metadata(installed, monkeypatch):
    project, root, config = installed
    downloads = {p.name: p.read_bytes() for p in (root / 'downloads').glob('*.zip')}
    clean.compact_exomiser(root, apply=True)
    (root / 'exomiser-cli-15.1.0/data/2602_hg38/synthetic.db').write_bytes(b'corrupt')
    cfg = json.loads(config.read_text())
    cfg['annotation'].update(exomiser_data_base_url='https://example.test',
        exomiser_cli_url='https://example.test/exomiser-cli-15.1.0-distribution.zip')
    atomic_write_json(config, cfg)
    monkeypatch.setattr(resources, '_download', lambda url, path: path.write_bytes(downloads[path.name]))
    resources.install_exomiser(config)
    resources.verify_exomiser_install(config)
    assert not (root / 'archive_compaction.json').exists()
    assert len(list((root / 'compaction_history').glob('*.json'))) == 2


@pytest.mark.parametrize('relative', ['/', '..', '../other', '/tmp'])
def test_broad_or_traversing_cleanup_targets_are_rejected(tmp_path, relative):
    with pytest.raises(Track1Error):
        clean.safe_path(tmp_path, relative)


def test_cleanup_dry_run_and_exact_allowlist_preserve_unknown_files(tmp_path):
    cache = tmp_path / '.tools/pip-cache/cache.bin'
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b'disposable')
    evidence = tmp_path / 'work/private/read_evidence/keep.tsv'
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(b'unique evidence')
    assert clean.clean_disposable(root=tmp_path)['removed_files'] == 0
    assert cache.exists()
    assert clean.clean_disposable(root=tmp_path, apply=True)['removed_files'] == 1
    assert not cache.exists() and evidence.read_bytes() == b'unique evidence'


def test_cleanup_refuses_symlink_cache_without_following_it(tmp_path):
    keep = tmp_path / 'keep'
    keep.mkdir()
    (keep / 'file').write_bytes(b'preserve')
    (tmp_path / '.tools').mkdir()
    (tmp_path / '.tools/pip-cache').symlink_to(keep, target_is_directory=True)
    with pytest.raises(Track1Error, match='symlink'):
        clean.clean_disposable(root=tmp_path, apply=True)
    assert (keep / 'file').read_bytes() == b'preserve'


def test_live_worker_prevents_cleanup(tmp_path, monkeypatch):
    from mva_runner import supervisor
    atomic_write_json(tmp_path / 'work/private/runner/state.json', {'stages': {'synthetic': {'child': {'pid': 123}}}})
    monkeypatch.setattr(supervisor, 'is_live', lambda identity: bool(identity))
    with pytest.raises(Track1Error, match='worker is live'):
        clean.clean_disposable(root=tmp_path, apply=True)
