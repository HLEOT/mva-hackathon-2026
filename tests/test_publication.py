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


def public_release_fixture(monkeypatch, tmp_path):
    report = {'file_count': 1, 'files': {'README.md': {'git_blob_sha': git_blob_sha(b'synthetic'), 'mode': '100644'}}}
    monkeypatch.setattr(publication, 'audit', lambda root: report)
    head, tree = 'a' * 40, 'b' * 40
    responses = {'': {'full_name': 'example/synthetic', 'private': False},
        '/git/ref/heads/main': {'object': {'sha': head}}, '/git/commits/' + head: {'tree': {'sha': tree}},
        '/git/trees/' + tree + '?recursive=1': {'truncated': False,
            'tree': [{'path': 'README.md', 'type': 'blob', **report['files']['README.md'],
                      'sha': report['files']['README.md']['git_blob_sha']}]}}
    monkeypatch.setattr(publication, '_github_json', lambda url: responses[url.removeprefix('https://api.github.com/repos/example/synthetic')])
    return responses


def test_live_release_receipt_requires_audited_remote_tree(monkeypatch, tmp_path):
    public_release_fixture(monkeypatch, tmp_path)
    receipt = publication.verify_release('example/synthetic', tmp_path)
    assert receipt['verified'] and receipt['commit'] == 'a' * 40
    assert (tmp_path / 'work/private/runner/code_release_verified.json').is_file()


@pytest.mark.parametrize('failure', ['private_repository', 'different_repository', 'truncated_tree', 'wrong_blob'])
def test_live_release_rejects_wrong_destination_or_content(monkeypatch, tmp_path, failure):
    responses = public_release_fixture(monkeypatch, tmp_path)
    if failure == 'private_repository': responses['']['private'] = True
    if failure == 'different_repository': responses['']['full_name'] = 'different/repository'
    remote = responses['/git/trees/' + 'b' * 40 + '?recursive=1']
    if failure == 'truncated_tree': remote['truncated'] = True
    if failure == 'wrong_blob': remote['tree'][0]['sha'] = 'c' * 40
    with pytest.raises(Track1Error):
        publication.verify_release('example/synthetic', tmp_path)
    assert not (tmp_path / 'work/private/runner/code_release_verified.json').exists()
