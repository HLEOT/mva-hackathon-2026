from __future__ import annotations

import gzip
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from mva_track1 import download
from mva_track1.common import Track1Error, sha256_file


def test_download_record_verifies_upstream_lfs_sha256(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "synthetic.bin"
    local.write_bytes(b"synthetic")
    monkeypatch.setattr(download, "PROJECT_ROOT", tmp_path)
    metadata = {
        "filename": local.name,
        "size": local.stat().st_size,
        "lfs": {"size": local.stat().st_size, "sha256": sha256_file(local)},
    }

    record = download._validated_download_record(local, metadata, "core")

    assert record["sha256"] == sha256_file(local)
    assert record["local_path"] == local.name
    metadata["lfs"]["sha256"] = "0" * 64
    with pytest.raises(Track1Error, match="Upstream LFS SHA-256 mismatch"):
        download._validated_download_record(local, metadata, "core")


def test_download_record_rejects_upstream_size_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = tmp_path / "synthetic.bin"
    local.write_bytes(b"synthetic")
    monkeypatch.setattr(download, "PROJECT_ROOT", tmp_path)

    with pytest.raises(Track1Error, match="Size mismatch"):
        download._validated_download_record(
            local,
            {"filename": local.name, "size": local.stat().st_size + 1},
            "core",
        )


def test_python_gzip_integrity_check_reads_through_footer(tmp_path: Path) -> None:
    path = tmp_path / "synthetic.vcf.gz"
    with gzip.open(path, "wb") as handle:
        handle.write(b"synthetic VCF payload\n")
    download._verify_gzip(path)

    truncated = path.read_bytes()[:-4]
    path.write_bytes(truncated)
    with pytest.raises(Track1Error, match="Corrupt gzip file"):
        download._verify_gzip(path)


def test_download_group_rejects_revision_change_before_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gated_root = tmp_path / "data" / "gated"
    source_dir = gated_root / "source"
    manifest_path = gated_root / "manifest.json"
    gated_root.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "repo_id": "example/synthetic",
                "repo_type": "dataset",
                "revision": "old-revision",
                "files": {},
            }
        ),
        encoding="utf-8",
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "huggingface": {
                    "repo_id": "example/synthetic",
                    "repo_type": "dataset",
                    "core_files": ["synthetic.bin"],
                    "fastq_files": [],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(download, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(download, "GATED_ROOT", gated_root)
    monkeypatch.setattr(download, "SOURCE_DIR", source_dir)
    monkeypatch.setattr(download, "MANIFEST_PATH", manifest_path)
    monkeypatch.setenv("HF_TOKEN", "synthetic-token")
    transfer_calls = []

    class FakeHfApi:
        def __init__(self, **_kwargs) -> None:
            pass

        def dataset_info(self, **_kwargs):
            return SimpleNamespace(
                sha="new-revision",
                siblings=[SimpleNamespace(rfilename="synthetic.bin")],
            )

    def fake_download(**kwargs):
        transfer_calls.append(kwargs)
        raise AssertionError("download must not start across dataset revisions")

    fake_hub = types.ModuleType("huggingface_hub")
    fake_hub.HfApi = FakeHfApi
    fake_hub.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    with pytest.raises(Track1Error, match="Refusing to mix.*purge-gated"):
        download.download_group("core", config)

    assert transfer_calls == []
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["revision"] == (
        "old-revision"
    )
