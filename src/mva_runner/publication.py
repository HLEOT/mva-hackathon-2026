"""Build an explicit, audited code-only snapshot for publication.

This module does not create a repository or acquire credentials. The coding
agent can publish the approved snapshot with the connected GitHub tool; users
can use their own Git client. Both routes must verify the remote tree against
the per-file blob hashes before claiming a successful release.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now

ROOT_FILES = {'.gitignore', 'README.md', 'AGENTS.md', 'mva', 'mva-track1', 'pyproject.toml'}
CONFIG_FILES = {'config.yaml', 'execution.yaml', 'track2.yaml', 'proband.example.yaml'}
SECRET = re.compile(r'(?:hf_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|'
                    r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def allowed(path: str) -> bool:
    parts = Path(path).parts
    if not parts or any(p in {'.', '..'} or '.local.' in p for p in parts):
        return False
    if len(parts) == 1:
        return path in ROOT_FILES
    if parts[0] == 'config':
        return len(parts) == 2 and parts[1] in CONFIG_FILES
    if parts[0] in {'docs', 'prompts'}:
        return path.endswith('.md')
    if parts[0] in {'src', 'tests'}:
        return path.endswith('.py') or path == 'tests/fixtures/.gitkeep'
    if parts[0] == 'workflow':
        return path == 'workflow/Snakefile' or (parts[1] == 'envs' and path.endswith('.yaml')) or (
            parts[1] == 'rules' and path.endswith('.smk'))
    return path == 'submissions/.gitkeep'


def git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()


def audit(root: Path = PROJECT_ROOT) -> dict:
    paths = [root / name for name in sorted(ROOT_FILES)]
    for directory in ['config', 'docs', 'prompts', 'src', 'tests', 'workflow']:
        paths += [p for p in (root / directory).rglob('*') if p.is_file() and allowed(str(p.relative_to(root)))]
    paths.append(root / 'submissions/.gitkeep')
    findings, files = [], {}
    secret_values = []
    for p in (root / 'config').glob('*token*.local.*'):
        if p.is_file():
            value = p.read_text().strip()
            if len(value) >= 16:
                secret_values.append(value)
    # Unique full candidate identifiers, not common genes/HPO names, provide a
    # targeted extra check against accidentally pasting private final results.
    private_identifiers = []
    review = root / 'work/private/finalist_review.json'
    if review.exists():
        private_identifiers = [r['candidate_id'] for r in load_jsonish(review).get('selections', [])]
    for p in sorted(set(paths)):
        name = str(p.relative_to(root))
        if not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) or not allowed(name):
            findings.append({'path': name, 'reason': 'not_an_allowed_regular_file'})
            continue
        raw = p.read_bytes()
        if len(raw) > 2_000_000:
            findings.append({'path': name, 'reason': 'unexpectedly_large_code_file'})
            continue
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError:
            findings.append({'path': name, 'reason': 'unexpected_binary_content'})
            continue
        if SECRET.search(text) or any(value in text for value in secret_values):
            findings.append({'path': name, 'reason': 'credential_pattern'})
        if any(identifier in text for identifier in private_identifiers):
            findings.append({'path': name, 'reason': 'private_candidate_identifier'})
        files[name] = {'sha256': hashlib.sha256(raw).hexdigest(), 'git_blob_sha': git_blob_sha(raw), 'size': len(raw),
                       'mode': '100755' if p.stat().st_mode & 0o111 else '100644'}
    # Existing tracked paths also matter: an allowlisted new snapshot must not
    # quietly preserve forbidden files from a previous public/local commit.
    tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, check=True).stdout.decode().split('\0')
    findings += [{'path': name, 'reason': 'tracked_path_outside_allowlist'} for name in tracked if name and not allowed(name)]
    report = {'created_at': utc_now(), 'passed': not findings, 'files': files, 'findings': findings,
              'file_count': len(files), 'total_bytes': sum(v['size'] for v in files.values()),
              'excludes': ['gated_data', 'private_results', 'credentials', 'weights', 'environments', 'logs', 'caches']}
    atomic_write_json(root / 'work/private/runner/release_audit.json', report)
    if findings:
        raise Track1Error('Code-only release audit failed; findings are retained in the private audit receipt')
    return report


def payload(root: Path = PROJECT_ROOT) -> dict:
    report = audit(root)
    entries = []
    for name, metadata in report['files'].items():
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise Track1Error('Publication path changed after the privacy audit')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != metadata['sha256']:
            raise Track1Error('Publication content changed after the privacy audit')
        entries.append({'path': name, 'mode': metadata['mode'], 'type': 'blob', 'content': raw.decode('utf-8')})
    return {'audit': report, 'tree_elements': entries}


def verify_tree(tree: list[dict], report: dict) -> None:
    if any(entry['type'] not in {'blob', 'tree'} for entry in tree):
        raise Track1Error('Remote release contains an unexpected Git object type')
    if len({entry['path'] for entry in tree}) != len(tree):
        raise Track1Error('Remote release contains duplicate paths')
    blobs = {entry['path']: entry for entry in tree if entry['type'] == 'blob'}
    expected_directories = {str(parent) for path in report['files'] for parent in Path(path).parents
                            if str(parent) != '.'}
    if any(entry['type'] == 'tree' and entry['path'] not in expected_directories for entry in tree):
        raise Track1Error('Remote release contains an unexpected directory')
    if set(blobs) != set(report['files']):
        raise Track1Error('Remote release file set differs from the audited snapshot')
    for name, expected in report['files'].items():
        if blobs[name]['sha'] != expected['git_blob_sha'] or blobs[name]['mode'] != expected['mode']:
            raise Track1Error('Remote release content or executable mode differs from the audited snapshot')


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--payload', action='store_true', help='Emit audited public code only for a release tool')
    args = parser.parse_args()
    if args.payload:
        print(json.dumps(payload()))
    else:
        report = audit()
        print(json.dumps({k: report[k] for k in ['passed', 'file_count', 'total_bytes']}))
