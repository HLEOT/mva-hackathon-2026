"""Preflight tests mock all network calls and use no real credentials or data."""
import json
from types import SimpleNamespace

import pytest
import requests

from mva_runner import preflight

LIMITS = {"cpus": 112, "memory_gib": 400, "additional_disk_bytes": 400_000_000_000, "disk_reserve_bytes": 10_000_000_000}


@pytest.mark.parametrize("key,value", [("cpus", 113), ("memory_gib", 401), ("additional_disk_bytes", 400_000_000_001),
                                      ("cpus", 0), ("cpus", True), ("memory_gib", "400"), ("disk_reserve_bytes", -1),
                                      ("additional_disk_bytes", 0), ("disk_reserve_bytes", 400_000_000_000)])
def test_execution_configuration_cannot_enlarge_authorisation(key, value):
    assert preflight.limits_valid(LIMITS)
    assert not preflight.limits_valid({**LIMITS, key: value})


@pytest.mark.parametrize("disk", [250_000_000_000, 300_000_000_000, 400_000_000_000])
def test_smaller_allowances_and_exact_approved_boundary_are_valid(disk):
    # Raising the ceiling does not require a smaller installation to consume it.
    assert preflight.limits_valid({**LIMITS, "additional_disk_bytes": disk})


def test_hf_authentication_requires_matching_identity_and_gated_file_access(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("HF_TOKEN", "synthetic-read-credential")
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        assert kwargs["allow_redirects"] is False
        assert kwargs["timeout"] == (10, 20)
        data = {"name": "synthetic-user"} if url.endswith("whoami-v2") else {"id": "synthetic/dataset", "sha": "a" * 40}
        return SimpleNamespace(status_code=200, json=lambda: data)
    monkeypatch.setattr(preflight.requests, "get", get)
    monkeypatch.setattr(preflight, "probe_gated_file", lambda *args: True)
    dataset = {"repo_id": "synthetic/dataset", "core_files": ["synthetic.vcf"]}
    report = preflight.hf_authentication("synthetic-user", dataset)
    assert report["status"] == "verified" and report["pinned_file_metadata_access"]
    assert "synthetic-read-credential" not in json.dumps(report)
    assert len(calls) == 2
    monkeypatch.setattr(preflight, "probe_gated_file", lambda *args: False)
    assert preflight.hf_authentication("synthetic-user", dataset)["status"] == "gated_file_access_not_verified"
    calls.clear()
    assert preflight.hf_authentication("different-user", dataset)["status"] == "identity_mismatch"
    assert len(calls) == 1


def test_network_error_does_not_expose_credential_or_exception_message(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "synthetic-read-credential")
    def failed(*args, **kwargs):
        raise requests.Timeout("private diagnostic with synthetic-read-credential")
    monkeypatch.setattr(preflight.requests, "get", failed)
    report = preflight.hf_authentication("synthetic-user", {"repo_id": "synthetic/dataset"})
    assert report == {"status": "verification_failed", "error_category": "Timeout"}


def test_destination_must_be_exact_public_repository(monkeypatch):
    monkeypatch.setattr(preflight.requests, "get", lambda *args, **kwargs: SimpleNamespace(
        status_code=200, json=lambda: {"full_name": "synthetic/code", "private": False}))
    assert preflight.github_destination("synthetic/code")["status"] == "public_destination_verified"
    assert preflight.github_destination("another/code")["status"] == "public_destination_mismatch"
    assert preflight.github_destination("https://untrusted.test")["status"] == "invalid_repository_identifier"
