"""Synthetic upstream metadata: no challenge or patient files in tests."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from mva_runner import official
from mva_track1.common import Track1Error

TEMPLATE = "static/templates/methods_description_form.xlsx"


def info(revision, raw=b"synthetic workbook", lfs=False):
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    return SimpleNamespace(sha=revision, siblings=[SimpleNamespace(rfilename=TEMPLATE,
        size=len(raw), blob_id=blob, lfs={"sha256": hashlib.sha256(raw).hexdigest()} if lfs else None)])


def setup(monkeypatch, tmp_path, current=None, pinned=None):
    monkeypatch.setattr(official, "ROOT", tmp_path)
    current = current or info("a" * 40)
    class API:
        def __init__(self, token):
            assert token is False

        def repo_info(self, repository, **kwargs):
            assert repository == official.REPOSITORY
            return pinned if kwargs.get("revision") else current
    monkeypatch.setattr("huggingface_hub.HfApi", API)
    monkeypatch.setattr(official, "_download", lambda url, target: target.write_bytes(b"synthetic workbook"))


@pytest.mark.parametrize("lfs", [False, True])
def test_download_matches_upstream_digest(monkeypatch, tmp_path, lfs):
    setup(monkeypatch, tmp_path, info("a" * 40, lfs=lfs))
    official.prepare()
    receipt = json.loads((tmp_path / "manifest.json").read_text())
    assert receipt["current_requirements_check"]["selected_sources_unchanged"]
    assert receipt["artifacts"][TEMPLATE]["upstream"]["algorithm"] == ("sha256" if lfs else "git_blob_sha1")


def test_cached_template_tampering_is_not_blessed_with_a_new_hash(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    official.prepare()
    target = tmp_path / TEMPLATE
    target.write_bytes(b"tampered  workbook")
    with pytest.raises(Track1Error, match="differs from upstream checksum"):
        official.prepare()
    assert target.read_bytes() == b"tampered  workbook"


def test_changed_requirements_block_without_repinning(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    official.prepare()
    setup(monkeypatch, tmp_path, info("b" * 40, b"new official bytes"), info("a" * 40))
    with pytest.raises(Track1Error, match="requirements or templates changed"):
        official.prepare()
    assert json.loads((tmp_path / "source_lock.json").read_text())["revision"] == "a" * 40
    assert json.loads((tmp_path / "current_requirements_check.json").read_text())["changed_paths"] == [TEMPLATE]


def test_unrelated_upstream_commit_keeps_pinned_sources(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    official.prepare()
    setup(monkeypatch, tmp_path, info("b" * 40), info("a" * 40))
    official.prepare()
    receipt = json.loads((tmp_path / "manifest.json").read_text())
    assert receipt["revision"] == "a" * 40
    assert receipt["current_requirements_check"]["current_revision"] == "b" * 40


def test_unsafe_locked_paths_are_rejected(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    (tmp_path / "source_lock.json").write_text(json.dumps({"repository": official.REPOSITORY,
        "revision": "a" * 40, "files": ["static/templates/../../outside"]}))
    with pytest.raises(Track1Error, match="Invalid official source lock"):
        official.prepare()
