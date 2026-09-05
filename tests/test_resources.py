from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from mva_track1.common import Track1Error
from mva_track1 import resources
from mva_track1.resources import _download, _extract_zip_safely


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int, headers: dict[str, str]) -> None:
        super().__init__(body)
        self.status = status
        self.headers = headers

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def test_download_retries_truncated_response_with_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    responses = [
        FakeResponse(b"abcd", 200, {"Content-Length": "8"}),
        FakeResponse(
            b"efgh",
            206,
            {"Content-Length": "4", "Content-Range": "bytes 4-7/8"},
        ),
    ]
    requests = []
    timeouts = []

    def fake_urlopen(request, **kwargs):
        requests.append(request)
        timeouts.append(kwargs.get("timeout"))
        return responses.pop(0)

    monkeypatch.setattr(resources.urllib.request, "urlopen", fake_urlopen)
    destination = tmp_path / "resource.bin"
    _download(
        "https://example.test/resource.bin",
        destination,
        max_attempts=2,
        retry_delay=0,
    )

    assert destination.read_bytes() == b"abcdefgh"
    assert requests[0].get_header("Range") is None
    assert requests[1].get_header("Range") == "bytes=4-"
    assert timeouts == [60.0, 60.0]
    assert not (tmp_path / "resource.bin.part").exists()


def test_download_appends_preexisting_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "resource.bin"
    partial = tmp_path / "resource.bin.part"
    partial.write_bytes(b"abcd")
    response = FakeResponse(
        b"efgh",
        206,
        {"Content-Length": "4", "Content-Range": "bytes 4-7/8"},
    )
    requests = []

    def fake_urlopen(request, **_kwargs):
        requests.append(request)
        return response

    monkeypatch.setattr(resources.urllib.request, "urlopen", fake_urlopen)
    _download(
        "https://example.test/resource.bin",
        destination,
        max_attempts=1,
        retry_delay=0,
    )

    assert requests[0].get_header("Range") == "bytes=4-"
    assert destination.read_bytes() == b"abcdefgh"
    assert not partial.exists()


def test_download_rejects_mismatched_content_range_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "resource.bin"
    partial = tmp_path / "resource.bin.part"
    partial.write_bytes(b"abcd")
    response = FakeResponse(
        b"defgh",
        206,
        {"Content-Length": "5", "Content-Range": "bytes 3-7/8"},
    )
    monkeypatch.setattr(
        resources.urllib.request,
        "urlopen",
        lambda _request, **_kwargs: response,
    )

    with pytest.raises(Track1Error, match="Unexpected Content-Range"):
        _download(
            "https://example.test/resource.bin",
            destination,
            max_attempts=1,
            retry_delay=0,
        )

    assert partial.read_bytes() == b"abcd"
    assert not destination.exists()


def test_download_rejects_ignored_range_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "resource.bin"
    partial = tmp_path / "resource.bin.part"
    partial.write_bytes(b"abcd")
    response = FakeResponse(b"abcdefgh", 200, {"Content-Length": "8"})
    monkeypatch.setattr(
        resources.urllib.request,
        "urlopen",
        lambda _request, **_kwargs: response,
    )

    with pytest.raises(Track1Error, match="ignored byte-range"):
        _download(
            "https://example.test/resource.bin",
            destination,
            max_attempts=1,
            retry_delay=0,
        )

    assert partial.read_bytes() == b"abcd"
    assert not destination.exists()


def test_download_promotes_complete_partial_after_http_416(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "resource.bin"
    partial = tmp_path / "resource.bin.part"
    partial.write_bytes(b"abcdefgh")

    def fake_urlopen(_request, **_kwargs):
        raise resources.urllib.error.HTTPError(
            "https://example.test/resource.bin",
            416,
            "Range Not Satisfiable",
            {"Content-Range": "bytes */8"},
            None,
        )

    monkeypatch.setattr(resources.urllib.request, "urlopen", fake_urlopen)
    _download(
        "https://example.test/resource.bin",
        destination,
        max_attempts=1,
        retry_delay=0,
    )

    assert destination.read_bytes() == b"abcdefgh"
    assert not partial.exists()


def test_download_rejects_mismatched_http_416_without_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "resource.bin"
    partial = tmp_path / "resource.bin.part"
    partial.write_bytes(b"abcd")
    attempts = 0

    def fake_urlopen(_request, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise resources.urllib.error.HTTPError(
            "https://example.test/resource.bin",
            416,
            "Range Not Satisfiable",
            {"Content-Range": "bytes */8"},
            None,
        )

    monkeypatch.setattr(resources.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(Track1Error, match="Unexpected HTTP 416 response"):
        _download(
            "https://example.test/resource.bin",
            destination,
            max_attempts=3,
            retry_delay=0,
        )

    assert attempts == 1
    assert partial.read_bytes() == b"abcd"
    assert not destination.exists()


def test_download_rejects_http_404_without_retrying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "resource.bin"
    partial = tmp_path / "resource.bin.part"
    partial.write_bytes(b"abcd")
    attempts = 0

    def fake_urlopen(_request, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise resources.urllib.error.HTTPError(
            "https://example.test/resource.bin",
            404,
            "Not Found",
            {},
            None,
        )

    monkeypatch.setattr(resources.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(Track1Error, match="HTTP 404 is not retryable"):
        _download(
            "https://example.test/resource.bin",
            destination,
            max_attempts=4,
            retry_delay=0,
        )

    assert attempts == 1
    assert partial.read_bytes() == b"abcd"
    assert not destination.exists()


def test_download_retries_transient_http_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = FakeResponse(b"abcdefgh", 200, {"Content-Length": "8"})
    attempts = 0

    def fake_urlopen(_request, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise resources.urllib.error.HTTPError(
                "https://example.test/resource.bin",
                503,
                "Service Unavailable",
                {},
                None,
            )
        return response

    monkeypatch.setattr(resources.urllib.request, "urlopen", fake_urlopen)
    destination = tmp_path / "resource.bin"
    _download(
        "https://example.test/resource.bin",
        destination,
        max_attempts=2,
        retry_delay=0,
    )

    assert attempts == 2
    assert destination.read_bytes() == b"abcdefgh"


def test_reference_resource_verification_checks_manifest_and_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resources, "PROJECT_ROOT", tmp_path)
    manifest_path = tmp_path / "public" / "manifest.json"
    monkeypatch.setattr(resources, "RESOURCE_MANIFEST", manifest_path)
    fasta = tmp_path / "public" / "reference.fa"
    paths = (fasta, Path(f"{fasta}.fai"), fasta.with_suffix(".dict"))
    for index, path in enumerate(paths, 1):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes([index]) * index)
    records = {
        str(path.relative_to(tmp_path)): {
            "size": path.stat().st_size,
            "sha256": resources.sha256_file(path),
        }
        for path in paths
    }
    manifest_path.write_text(
        json.dumps({"reference": {"files": records}}), encoding="utf-8"
    )
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps({"reference": {"fasta": "public/reference.fa"}}),
        encoding="utf-8",
    )

    resources.verify_reference_resources(config)
    fasta.write_bytes(b"changed")
    with pytest.raises(Track1Error, match="size mismatch"):
        resources.verify_reference_resources(config)


def test_annotation_resource_verifiers_require_real_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(resources, "PROJECT_ROOT", tmp_path)
    config = tmp_path / "config.json"
    config.write_text(
        json.dumps(
            {
                "annotation": {
                    "vep_version": 116,
                    "vep_cache_dir": "vep",
                    "exomiser_version": "15.1.0",
                    "exomiser_data_version": "2602",
                    "exomiser_dir": "exomiser",
                }
            }
        ),
        encoding="utf-8",
    )

    vep_cache = tmp_path / "vep" / "homo_sapiens_merged" / "116_GRCh38"
    vep_cache.mkdir(parents=True)
    (vep_cache / "info.txt").write_text(
        "# Synthetic metadata in deliberately non-canonical field order\n"
        "source_refseq\tGCF_synthetic\n"
        "var_type\ttabix\n"
        "cache_version\t116\n"
        "assembly\tGRCh38\n"
        "source_gencode\tGENCODE synthetic\n"
        "species\thomo_sapiens\n",
        encoding="utf-8",
    )
    for chromosome in resources._VEP_PRIMARY_CHROMOSOMES:
        chromosome_dir = vep_cache / chromosome
        chromosome_dir.mkdir()
        index_name = "all_vars.gz.csi" if chromosome == "Y" else "all_vars.gz.tbi"
        for name in ("1-1000000.gz", "all_vars.gz", index_name):
            (chromosome_dir / name).write_bytes(b"synthetic")
    resources.verify_vep_cache(
        config, require_marker=False, require_manifest=False
    )
    with pytest.raises(Track1Error, match="marker is absent"):
        resources.verify_vep_cache(config)
    (tmp_path / "vep" / ".v116_merged_complete").write_text(
        "complete\n", encoding="utf-8"
    )
    with pytest.raises(Track1Error, match="install manifest is absent"):
        resources.verify_vep_cache(config)
    vep_manifest_path = resources.create_vep_install_manifest(config)
    vep_manifest = json.loads(vep_manifest_path.read_text(encoding="utf-8"))
    assert vep_manifest["version"] == "116"
    assert vep_manifest["assembly"] == "GRCh38"
    assert vep_manifest["species"] == "homo_sapiens"
    assert vep_manifest["cache_relative_path"] == "homo_sapiens_merged/116_GRCh38"
    assert vep_manifest["release_url"] == (
        "https://ftp.ensembl.org/pub/release-116/variation/indexed_vep_cache/"
        "homo_sapiens_merged_vep_116_GRCh38.tar.gz"
    )
    assert vep_manifest["primary_chromosomes"] == list(
        resources._VEP_PRIMARY_CHROMOSOMES
    )
    assert vep_manifest["file_count"] == 76
    assert vep_manifest["total_bytes"] > 0
    assert vep_manifest["info_txt_sha256"] == resources.sha256_file(
        vep_cache / "info.txt"
    )
    resources.verify_vep_cache(config)

    info_path = vep_cache / "info.txt"
    valid_info = info_path.read_text(encoding="utf-8")
    invalid_metadata = [
        ("species\thomo_sapiens", "species\tmus_musculus", "species metadata"),
        ("assembly\tGRCh38", "assembly\tGRCh37", "assembly metadata"),
        ("cache_version\t116", "cache_version\t115", "version metadata"),
        ("source_refseq\tGCF_synthetic\n", "", "merged human cache"),
    ]
    for original, replacement, message in invalid_metadata:
        info_path.write_text(
            valid_info.replace(original, replacement), encoding="utf-8"
        )
        with pytest.raises(Track1Error, match=message):
            resources.verify_vep_cache(config, require_manifest=False)
    info_path.write_text(valid_info, encoding="utf-8")

    chromosome_dir = vep_cache / "22"
    hidden_chromosome_dir = vep_cache / "22.missing"
    chromosome_dir.rename(hidden_chromosome_dir)
    with pytest.raises(Track1Error, match="missing primary chromosome.*22"):
        resources.verify_vep_cache(config, require_manifest=False)
    hidden_chromosome_dir.rename(chromosome_dir)

    chromosome_index = vep_cache / "X" / "all_vars.gz.tbi"
    chromosome_index.unlink()
    with pytest.raises(Track1Error, match="chromosome X.*variation index"):
        resources.verify_vep_cache(config, require_manifest=False)
    chromosome_index.write_bytes(b"synthetic")

    transcript_shard = vep_cache / "MT" / "1-1000000.gz"
    transcript_shard.unlink()
    with pytest.raises(Track1Error, match="chromosome MT.*transcript shard"):
        resources.verify_vep_cache(config, require_manifest=False)
    transcript_shard.write_bytes(b"synthetic")

    info_path.write_text(valid_info + "# changed after install\n", encoding="utf-8")
    with pytest.raises(Track1Error, match="current cache: info_txt_sha256"):
        resources.verify_vep_cache(config)
    info_path.write_text(valid_info, encoding="utf-8")

    unexpected_file = vep_cache / "1" / "unexpected.cache"
    unexpected_file.write_bytes(b"changed")
    with pytest.raises(Track1Error, match="current cache: file_count"):
        resources.verify_vep_cache(config)
    unexpected_file.unlink()
    resources.verify_vep_cache(config)

    exomiser = tmp_path / "exomiser"
    downloads = exomiser / "downloads"
    downloads.mkdir(parents=True)
    names = [
        "exomiser-cli-15.1.0-distribution.zip",
        "2602_hg38.zip",
        "2602_phenotype.zip",
    ]
    records = []
    for name in names:
        archive = downloads / name
        archive.write_bytes(b"x")
        records.append(
            {
                "file": name,
                "size": 1,
                "sha256": resources.sha256_file(archive),
            }
        )
    (exomiser / ".complete").write_text("complete\n", encoding="utf-8")
    (exomiser / "install_manifest.json").write_text(
        json.dumps(
            {
                "version": "15.1.0",
                "data_version": "2602",
                "archives": records,
            }
        ),
        encoding="utf-8",
    )
    cli_root = exomiser / "exomiser-cli-15.1.0"
    cli_root.mkdir()
    (cli_root / "exomiser-cli-15.1.0.jar").write_bytes(b"jar")
    for name in ("2602_hg38", "2602_phenotype"):
        data_dir = cli_root / "data" / name
        data_dir.mkdir(parents=True)
        (data_dir / "synthetic.dat").write_bytes(b"data")

    resources.verify_exomiser_install(config)
    mutated_archive = downloads / "2602_hg38.zip"
    mutated_archive.write_bytes(b"y")
    with pytest.raises(Track1Error, match="archive checksum mismatch"):
        resources.verify_exomiser_install(config)
    resources.verify_exomiser_install(config, check_hashes=False)
    mutated_archive.write_bytes(b"x")
    (downloads / "2602_hg38.zip.part").write_bytes(b"partial")
    with pytest.raises(Track1Error, match="partial archive remains"):
        resources.verify_exomiser_install(config)


def test_safe_zip_is_extracted(tmp_path: Path) -> None:
    archive = tmp_path / "safe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("release/data.txt", "ok")
    destination = tmp_path / "output"
    _extract_zip_safely(archive, destination)
    assert (destination / "release" / "data.txt").read_text(encoding="utf-8") == "ok"


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("../escape.txt", "no")
    with pytest.raises(Track1Error, match="outside destination"):
        _extract_zip_safely(archive, tmp_path / "output")
    assert not (tmp_path / "escape.txt").exists()
