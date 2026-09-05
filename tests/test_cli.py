from __future__ import annotations

import json
from pathlib import Path

import pytest

from mva_track1 import cli
from mva_track1.common import Track1Error


def test_validated_state_distinguishes_wait_invalid_and_ready(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    assert cli._validated_state(artifact) == "WAIT"
    artifact.write_text("present\n", encoding="utf-8")

    def invalid() -> None:
        raise Track1Error("synthetic invalid state")

    assert cli._validated_state(artifact, invalid) == "INVALID"
    assert cli._validated_state(artifact, lambda: None) == "READY"


def test_unreviewed_finalists_block_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates = tmp_path / "candidates.tsv"
    candidates.write_text("candidate_id\nsynthetic-candidate\n", encoding="utf-8")
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        "synthetic-candidate\tYES\t1\tprimary\tREVIEW REQUIRED\n",
        encoding="utf-8",
    )
    calls = []
    monkeypatch.setattr(cli, "CANDIDATES", candidates)
    monkeypatch.setattr(cli, "FINALISTS", finalists)
    monkeypatch.setattr(cli, "download_group", lambda group: calls.append(group))
    monkeypatch.setattr(cli, "_snakemake", lambda *_args: calls.append("snakemake"))

    with pytest.raises(Track1Error, match="lacks a reviewed rationale"):
        cli.main(["validate-finalists", "--cores", "1"])

    assert calls == []


def test_package_rejects_invalid_read_validation_before_building(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates = tmp_path / "candidates.tsv"
    candidates.write_text("candidate_id\nsynthetic-candidate\n", encoding="utf-8")
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        "synthetic-candidate\tYES\t1\tprimary\tReviewed evidence\n",
        encoding="utf-8",
    )
    validation = tmp_path / "read_validation.tsv"
    validation.write_text("candidate_id\nsynthetic-candidate\n", encoding="utf-8")
    manifest = tmp_path / "final_run_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    identity = tmp_path / "submission.local.json"
    identity.write_text(
        '{"hf_username": "synthetic-user", "github_url": "https://github.com/example/repo"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "CANDIDATES", candidates)
    monkeypatch.setattr(cli, "FINALISTS", finalists)
    monkeypatch.setattr(cli, "VALIDATION", validation)
    monkeypatch.setattr(cli, "FINAL_RUN_MANIFEST", manifest)
    monkeypatch.setattr(cli, "SUBMISSION_CONFIG", identity)

    def blocked_readiness(*, verify_large_hashes: bool) -> None:
        assert verify_large_hashes is True
        raise Track1Error("Raw-read validation schema does not match")

    monkeypatch.setattr(cli, "_assert_package_readiness", blocked_readiness)

    with pytest.raises(Track1Error, match="schema"):
        cli._package()


@pytest.mark.parametrize(
    "github_url",
    [
        "https://github.com/example/project",
        "https://github.com/example/project/",
        "https://github.com/example/project.git",
        "https://github.com/example/project.git/",
        "https://github.com/example-org/.github",
    ],
)
def test_submission_identity_accepts_canonical_github_repository_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    github_url: str,
) -> None:
    identity = tmp_path / "submission.local.json"
    identity.write_text(
        json.dumps({"hf_username": "synthetic-user", "github_url": github_url}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "SUBMISSION_CONFIG", identity)

    assert cli._submission_identity() == ("synthetic-user", github_url)


@pytest.mark.parametrize(
    "github_url",
    [
        "https://github.com/",
        "https://github.com/example",
        "http://github.com/example/project",
        "https://www.github.com/example/project",
        "https://github.com/example/project/issues",
        "https://github.com/example/project?tab=readme",
        "https://github.com/example/project#readme",
        "https://github.com/REPLACE/REPLACE",
        "https://github.com/example--owner/project",
        "https://github.com/example-/project",
        "https://github.com/example/..",
    ],
)
def test_submission_identity_rejects_noncanonical_github_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    github_url: str,
) -> None:
    identity = tmp_path / "submission.local.json"
    identity.write_text(
        json.dumps({"hf_username": "synthetic-user", "github_url": github_url}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "SUBMISSION_CONFIG", identity)

    with pytest.raises(Track1Error, match="GitHub repository URL"):
        cli._submission_identity()


def test_package_prints_each_submission_artifact_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    identity = tmp_path / "submission.local.json"
    identity.write_text(
        json.dumps(
            {
                "hf_username": "Synthetic-User",
                "github_url": "https://github.com/example/project",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "SUBMISSION_CONFIG", identity)
    (tmp_path / "submissions").mkdir()
    monkeypatch.setattr(cli, "_assert_package_readiness", lambda **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "build_submission",
        lambda _candidates, _finalists, output, _validation: output.write_text(
            "synthetic\n", encoding="utf-8"
        ),
    )
    monkeypatch.setattr(cli, "validate_submission_file", lambda _path: None)
    monkeypatch.setattr(
        cli,
        "generate_markdown",
        lambda _candidates, _finalists, _validation, _manifest, output, _github: output.write_text(
            "synthetic\n", encoding="utf-8"
        ),
    )
    monkeypatch.setattr(
        cli,
        "markdown_to_pdf",
        lambda _markdown, output: output.write_bytes(b"synthetic"),
    )
    monkeypatch.setattr(cli, "audit_tracked_files", lambda: None)

    cli._package()

    output = capsys.readouterr().out
    submissions = tmp_path / "submissions"
    assert f"CSV submission: {submissions / 'synthetic-user_track1-ranked.csv'}" in output
    assert f"Markdown report: {submissions / 'synthetic-user_track1_report.md'}" in output
    assert f"PDF report: {submissions / 'synthetic-user_track1_report.pdf'}" in output
    assert f"Convenience ZIP: {submissions / 'synthetic-user_track1_bundle.zip'}" in output


def test_package_readiness_runs_all_read_only_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidates = tmp_path / "candidates.tsv"
    validation = tmp_path / "read_validation.tsv"
    manifest = tmp_path / "final_run_manifest.json"
    for path in (candidates, validation, manifest):
        path.write_text("synthetic\n", encoding="utf-8")
    monkeypatch.setattr(cli, "CANDIDATES", candidates)
    monkeypatch.setattr(cli, "VALIDATION", validation)
    monkeypatch.setattr(cli, "FINAL_RUN_MANIFEST", manifest)
    calls: list[str] = []
    monkeypatch.setattr(
        cli, "validate_proband_config", lambda path: calls.append("phenotype")
    )
    monkeypatch.setattr(
        cli, "reviewed_finalists", lambda finalists, ranked: calls.append("finalists")
    )
    monkeypatch.setattr(
        cli,
        "validate_read_validation",
        lambda artifact, finalists, ranked: calls.append("validation"),
    )
    monkeypatch.setattr(
        cli,
        "_environment_provenance",
        lambda: (
            {
                name: {"status": "ready"}
                for name in ("scheduler", "launcher", "hts", "annotation", "reads")
            },
            {
                name: {"status": "ready"}
                for name in cli.FINAL_MANIFEST_REQUIRED_TOOLS
            },
        ),
    )
    monkeypatch.setattr(
        cli,
        "verify_core",
        lambda *, write_receipt: calls.append(f"core:{write_receipt}"),
    )
    monkeypatch.setattr(cli, "verify_reference_resources", lambda: calls.append("reference"))
    monkeypatch.setattr(cli, "verify_vep_cache", lambda: calls.append("vep"))
    monkeypatch.setattr(cli, "verify_exomiser_install", lambda: calls.append("exomiser"))

    def validate_manifest(path: Path, evidence: Path, *, verify_large_hashes: bool) -> None:
        assert verify_large_hashes is True
        calls.append("manifest:full")

    monkeypatch.setattr(cli, "validate_final_run_manifest", validate_manifest)

    cli._assert_package_readiness(verify_large_hashes=True)

    assert calls == [
        "phenotype",
        "finalists",
        "validation",
        "core:False",
        "reference",
        "vep",
        "exomiser",
        "manifest:full",
    ]


def test_status_marks_malformed_private_artifacts_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "reference": {"fasta": "resources/public/reference/ref.fa"},
                "annotation": {
                    "vep_cache_dir": "resources/public/vep",
                    "vep_version": "116",
                    "exomiser_dir": "resources/public/exomiser",
                },
            }
        ),
        encoding="utf-8",
    )
    candidates = tmp_path / "candidates.tsv"
    candidates.write_text("candidate_id\nsynthetic-candidate\n", encoding="utf-8")
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        "synthetic-candidate\tYES\t1\tprimary\tReviewed evidence\n",
        encoding="utf-8",
    )
    validation = tmp_path / "read_validation.tsv"
    validation.write_text("candidate_id\nsynthetic-candidate\n", encoding="utf-8")
    manifest = tmp_path / "final_run_manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    missing = tmp_path / "missing"
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "DEFAULT_CONFIG", config)
    monkeypatch.setattr(cli, "CANDIDATES", candidates)
    monkeypatch.setattr(cli, "FINALISTS", finalists)
    monkeypatch.setattr(cli, "VALIDATION", validation)
    monkeypatch.setattr(cli, "FINAL_RUN_MANIFEST", manifest)
    monkeypatch.setattr(cli, "SUBMISSION_CONFIG", missing)
    monkeypatch.setattr(cli, "PROBAND_CONFIG", missing)
    monkeypatch.setattr(cli, "MANIFEST_PATH", missing)
    monkeypatch.setattr(
        cli,
        "_environment_provenance",
        lambda: (
            {
                name: {"status": "environment_not_built"}
                for name in ("scheduler", "launcher", "hts", "annotation", "reads")
            },
            {},
        ),
    )

    cli._status()

    output = capsys.readouterr().out
    assert "INVALID raw-read validation" in output
    assert "INVALID final run manifest" in output


def test_status_skips_large_public_resource_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "reference": {"fasta": "resources/public/reference/ref.fa"},
                "annotation": {
                    "vep_cache_dir": "resources/public/vep",
                    "vep_version": "116",
                    "exomiser_dir": "resources/public/exomiser",
                },
            }
        ),
        encoding="utf-8",
    )
    reference = tmp_path / "resources/public/reference/ref.fa"
    exomiser_marker = tmp_path / "resources/public/exomiser/.complete"
    reference.parent.mkdir(parents=True)
    exomiser_marker.parent.mkdir(parents=True)
    reference.write_text("synthetic\n", encoding="utf-8")
    exomiser_marker.write_text("complete\n", encoding="utf-8")
    calls: list[tuple[str, bool]] = []
    missing = tmp_path / "missing"
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli, "DEFAULT_CONFIG", config)
    monkeypatch.setattr(cli, "MANIFEST_PATH", missing)
    monkeypatch.setattr(cli, "CANDIDATES", missing)
    monkeypatch.setattr(cli, "FINALISTS", missing)
    monkeypatch.setattr(cli, "VALIDATION", missing)
    monkeypatch.setattr(cli, "FINAL_RUN_MANIFEST", missing)
    monkeypatch.setattr(cli, "SUBMISSION_CONFIG", missing)
    monkeypatch.setattr(cli, "PROBAND_CONFIG", missing)
    monkeypatch.setattr(
        cli,
        "verify_reference_resources",
        lambda *, check_hashes: calls.append(("reference", check_hashes)),
    )
    monkeypatch.setattr(
        cli,
        "verify_exomiser_install",
        lambda *, check_hashes: calls.append(("exomiser", check_hashes)),
    )
    monkeypatch.setattr(
        cli,
        "_environment_provenance",
        lambda: (
            {
                name: {"status": "environment_not_built"}
                for name in ("scheduler", "launcher", "hts", "annotation", "reads")
            },
            {},
        ),
    )

    cli._status()

    assert calls == [("reference", False), ("exomiser", False)]
