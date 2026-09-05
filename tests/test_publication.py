import hashlib
import pytest
from mva_runner import publication
from mva_runner.publication import allowed, git_blob_sha, verify_tree
from mva_track1.common import Track1Error


@pytest.mark.parametrize('name', ['data/gated/source/private.vcf', 'config/proband.local.yaml', 'config/hf_token.local.txt',
                                  'results/private/report.md', 'submissions/report.pdf', '.tools/model.gguf', 'logs/run.log'])
def test_private_material_is_outside_publication_allowlist(name):
    assert not allowed(name)


def test_remote_tree_must_match_exact_audited_files_bytes_and_modes():
    digest = git_blob_sha(b'synthetic\n')
    report = {'files': {'README.md': {'git_blob_sha': digest, 'mode': '100644'}}}
    entry = {'path': 'README.md', 'type': 'blob', 'sha': digest, 'mode': '100644'}
    verify_tree([entry], report)
    with pytest.raises(Track1Error):
        verify_tree([{**entry, 'sha': '0' * 40}], report)
    with pytest.raises(Track1Error):
        verify_tree([entry, {**entry, 'path': 'private.txt'}], report)
    for extra in [{**entry, 'path': 'module', 'type': 'commit'},
                  {**entry, 'path': 'empty', 'type': 'tree'}, entry]:
        with pytest.raises(Track1Error):
            verify_tree([entry, extra], report)


def test_payload_refuses_a_file_changed_after_the_audit(tmp_path, monkeypatch):
    path = tmp_path / 'README.md'
    path.write_text('unreviewed replacement\n')
    report = {'files': {'README.md': {'sha256': hashlib.sha256(b'audited original\n').hexdigest(), 'mode': '100644'}}}
    monkeypatch.setattr(publication, 'audit', lambda root: report)
    with pytest.raises(Track1Error, match='changed after'):
        publication.payload(tmp_path)
