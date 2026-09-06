from __future__ import annotations

import json
import os
import re
import shutil
import stat
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from .common import DEFAULT_CONFIG, PROJECT_ROOT, Track1Error, atomic_write_json, load_jsonish, sha256_file, utc_now


PUBLIC_ROOT = PROJECT_ROOT / "resources" / "public"
RESOURCE_MANIFEST = PUBLIC_ROOT / "manifest.json"


_CONTENT_RANGE_RE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VEP_TRANSCRIPT_SHARD_RE = re.compile(r"^\d+-\d+\.gz$")
_VEP_PRIMARY_CHROMOSOMES = tuple(str(number) for number in range(1, 23)) + (
    "X",
    "Y",
    "MT",
)


class _NonRetryableDownloadError(Track1Error):
    pass


def _download(
    url: str,
    destination: Path,
    *,
    max_attempts: int = 5,
    retry_delay: float = 1.0,
    timeout: float = 60.0,
) -> None:
    """Download atomically, retaining and safely resuming partial transfers."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        offset = partial.stat().st_size if partial.exists() else 0
        headers = {"User-Agent": "mva-track1/0.1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                content_length = response.headers.get("Content-Length")
                if offset and status != 206:
                    raise _NonRetryableDownloadError(
                        f"Server ignored byte-range request for {url}; "
                        f"partial file retained for resume: {partial}"
                    )

                if status == 206:
                    content_range = response.headers.get("Content-Range", "")
                    match = _CONTENT_RANGE_RE.fullmatch(content_range)
                    if match is None:
                        raise _NonRetryableDownloadError(
                            f"Invalid Content-Range for {url}: {content_range!r}; "
                            f"partial file retained for resume: {partial}"
                        )
                    start, end, total = (int(value) for value in match.groups())
                    if start != offset or end < start or total <= end:
                        raise _NonRetryableDownloadError(
                            f"Unexpected Content-Range for {url}: {content_range!r}; "
                            f"expected byte {offset}; partial file retained for resume: {partial}"
                        )
                    expected_size = total
                    mode = "ab" if offset else "wb"
                else:
                    expected_size = int(content_length) if content_length is not None else None
                    mode = "wb"

                with partial.open(mode) as output:
                    shutil.copyfileobj(response, output, length=8 * 1024 * 1024)

            if expected_size is not None and partial.stat().st_size != expected_size:
                raise Track1Error(
                    f"Incomplete download for {url}: expected {expected_size} bytes, "
                    f"received {partial.stat().st_size}"
                )
            os.replace(partial, destination)
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and offset:
                content_range = exc.headers.get("Content-Range", "")
                total = content_range.rsplit("/", 1)[-1]
                if total.isdigit() and offset == int(total):
                    os.replace(partial, destination)
                    return
                raise _NonRetryableDownloadError(
                    f"Unexpected HTTP 416 response for {url}: "
                    f"{content_range!r}; partial file retained for resume: {partial}"
                ) from exc
            if exc.code not in {408, 429} and not 500 <= exc.code <= 599:
                raise _NonRetryableDownloadError(
                    f"HTTP {exc.code} is not retryable for {url}; "
                    f"partial file retained if present: {partial}"
                ) from exc
            last_error = exc
        except _NonRetryableDownloadError:
            raise
        except Exception as exc:
            last_error = exc

        if attempt + 1 < max_attempts and retry_delay > 0:
            time.sleep(min(retry_delay * (2**attempt), 8.0))

    raise Track1Error(
        f"Failed to download {url} after {max_attempts} attempts: {last_error}. "
        f"Partial file retained for resume: {partial}"
    ) from last_error


def _nonempty_file(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def _read_vep_cache_info(path: Path) -> dict[str, str]:
    """Read VEP's tab-delimited info.txt while tolerating order and comments."""
    metadata: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise Track1Error(f"Unable to read VEP cache metadata: {path}") from exc

    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "\t" not in line:
            raise Track1Error(
                f"Malformed VEP cache metadata at info.txt line {line_number}"
            )
        key, value = (field.strip() for field in line.split("\t", 1))
        key = key.lower()
        if not key:
            raise Track1Error(
                f"Malformed VEP cache metadata at info.txt line {line_number}"
            )
        if key in metadata and metadata[key] != value:
            raise Track1Error(f"Conflicting VEP cache metadata field: {key}")
        metadata[key] = value
    return metadata


def _vep_cache_identity(
    config_path: Path | str,
) -> tuple[Path, Path, Path, Path, str, str, str]:
    config = load_jsonish(config_path)
    annotation = config["annotation"]
    version = str(annotation["vep_version"])
    species = str(annotation.get("vep_species", "homo_sapiens"))
    assembly = str(
        annotation.get(
            "vep_assembly", config.get("project", {}).get("assembly", "GRCh38")
        )
    )
    cache_type = str(annotation.get("vep_cache_type", "merged"))
    if (species, assembly, cache_type) != ("homo_sapiens", "GRCh38", "merged"):
        raise Track1Error(
            "This Track 1 workflow requires the homo_sapiens merged GRCh38 VEP cache"
        )
    root = PROJECT_ROOT / annotation["vep_cache_dir"]
    cache = root / f"{species}_{cache_type}" / f"{version}_{assembly}"
    marker = root / f".v{version}_{cache_type}_complete"
    manifest = root / "install_manifest.json"
    release_url = (
        f"https://ftp.ensembl.org/pub/release-{version}/variation/"
        f"indexed_vep_cache/{species}_{cache_type}_vep_{version}_{assembly}.tar.gz"
    )
    return root, cache, marker, manifest, version, assembly, release_url


def _vep_cache_inventory(cache: Path) -> tuple[int, int]:
    file_count = 0
    total_bytes = 0
    for path in cache.rglob("*"):
        if path.is_file():
            file_count += 1
            total_bytes += path.stat().st_size
    return file_count, total_bytes


def _vep_install_manifest_record(
    config_path: Path | str = DEFAULT_CONFIG,
) -> dict[str, object]:
    root, cache, _, _, version, assembly, release_url = _vep_cache_identity(
        config_path
    )
    file_count, total_bytes = _vep_cache_inventory(cache)
    return {
        "version": version,
        "assembly": assembly,
        "species": "homo_sapiens",
        "cache_type": "merged",
        "release_url": release_url,
        "cache_relative_path": str(cache.relative_to(root)),
        "info_txt_sha256": sha256_file(cache / "info.txt"),
        "primary_chromosomes": list(_VEP_PRIMARY_CHROMOSOMES),
        "file_count": file_count,
        "total_bytes": total_bytes,
    }


def create_vep_install_manifest(
    config_path: Path | str = DEFAULT_CONFIG,
) -> Path:
    """Write the public cache manifest only after structural verification."""
    verify_vep_cache(
        config_path,
        require_marker=False,
        require_manifest=False,
    )
    _, _, _, manifest_path, _, _, _ = _vep_cache_identity(config_path)
    record = _vep_install_manifest_record(config_path)
    record["created_at"] = utc_now()
    atomic_write_json(manifest_path, record, mode=0o644)
    return manifest_path


def verify_reference_resources(
    config_path: Path | str = DEFAULT_CONFIG,
    *,
    check_hashes: bool = True,
) -> None:
    cfg = load_jsonish(config_path)["reference"]
    fasta = PROJECT_ROOT / cfg["fasta"]
    files = (fasta, Path(f"{fasta}.fai"), fasta.with_suffix(".dict"))
    if not RESOURCE_MANIFEST.is_file():
        raise Track1Error("Public reference manifest is absent")
    manifest = load_jsonish(RESOURCE_MANIFEST).get("reference", {}).get("files", {})
    for path in files:
        if not _nonempty_file(path):
            raise Track1Error(f"Public reference artifact is missing or empty: {path}")
        relative = str(path.relative_to(PROJECT_ROOT))
        record = manifest.get(relative)
        if not record:
            raise Track1Error(f"Public reference manifest lacks: {relative}")
        if path.stat().st_size != int(record.get("size", -1)):
            raise Track1Error(f"Public reference size mismatch: {relative}")
        if check_hashes and sha256_file(path) != record.get("sha256"):
            raise Track1Error(f"Public reference checksum mismatch: {relative}")
        if Path(f"{path}.part").exists():
            raise Track1Error(f"Public reference partial remains: {relative}.part")


def verify_vep_cache(
    config_path: Path | str = DEFAULT_CONFIG,
    *,
    require_marker: bool = True,
    require_manifest: bool = True,
) -> None:
    root, cache, marker, manifest_path, version, _, _ = _vep_cache_identity(
        config_path
    )
    if require_marker and not marker.is_file():
        raise Track1Error("VEP completion marker is absent")
    info_path = cache / "info.txt"
    if not _nonempty_file(info_path):
        raise Track1Error("VEP merged cache info.txt is missing or empty")
    if (root / "tmp").exists():
        raise Track1Error("VEP temporary download directory remains")

    info = _read_vep_cache_info(info_path)
    if info.get("species") != "homo_sapiens":
        raise Track1Error("VEP cache species metadata does not match homo_sapiens")
    if info.get("assembly") != "GRCh38":
        raise Track1Error("VEP cache assembly metadata does not match GRCh38")
    if info.get("var_type") != "tabix":
        raise Track1Error("VEP cache var_type metadata does not identify an indexed cache")
    if not info.get("source_refseq") or not any(
        info.get(key) for key in ("source_gencode", "source_genebuild")
    ):
        raise Track1Error("VEP cache metadata does not identify a merged human cache")

    for key in ("cache_version", "vep_version"):
        reported = info.get(key)
        if reported is not None and reported.removeprefix("v") != version:
            raise Track1Error(
                f"VEP cache version metadata does not match configured version {version}"
            )
    if reported := info.get("source_ensembl"):
        release = re.match(r"^v?(\d+)(?:\D|$)", reported)
        if release is not None and release.group(1) != version:
            raise Track1Error(
                f"VEP cache Ensembl source does not match configured version {version}"
            )

    missing_chromosomes = [
        chromosome
        for chromosome in _VEP_PRIMARY_CHROMOSOMES
        if not (cache / chromosome).is_dir()
    ]
    if missing_chromosomes:
        raise Track1Error(
            "VEP merged cache is missing primary chromosome directories: "
            + ", ".join(missing_chromosomes)
        )

    for chromosome in _VEP_PRIMARY_CHROMOSOMES:
        chromosome_dir = cache / chromosome
        transcript_shards = (
            path
            for path in chromosome_dir.iterdir()
            if _VEP_TRANSCRIPT_SHARD_RE.fullmatch(path.name)
        )
        if not any(_nonempty_file(path) for path in transcript_shards):
            raise Track1Error(
                f"VEP cache chromosome {chromosome} has no nonempty transcript shard"
            )

        variation = chromosome_dir / "all_vars.gz"
        if not _nonempty_file(variation):
            raise Track1Error(
                f"VEP cache chromosome {chromosome} has no nonempty all_vars.gz"
            )
        indexes = (Path(f"{variation}.tbi"), Path(f"{variation}.csi"))
        if not any(_nonempty_file(path) for path in indexes):
            raise Track1Error(
                f"VEP cache chromosome {chromosome} has no nonempty variation index"
            )

    if not require_manifest:
        return
    if not _nonempty_file(manifest_path):
        raise Track1Error("VEP install manifest is absent")
    try:
        manifest = load_jsonish(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise Track1Error("VEP install manifest is unreadable or invalid") from exc
    expected = _vep_install_manifest_record(config_path)
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise Track1Error(f"VEP install manifest does not match current cache: {key}")
    if not isinstance(manifest.get("created_at"), str) or not manifest["created_at"]:
        raise Track1Error("VEP install manifest lacks a creation timestamp")


def verify_exomiser_install(
    config_path: Path | str = DEFAULT_CONFIG,
    *,
    check_hashes: bool = True,
) -> None:
    cfg = load_jsonish(config_path)["annotation"]
    version = str(cfg["exomiser_version"])
    data_version = str(cfg["exomiser_data_version"])
    root = PROJECT_ROOT / cfg["exomiser_dir"]
    if not _nonempty_file(root / ".complete"):
        raise Track1Error("Exomiser completion marker is absent")
    manifest_path = root / "install_manifest.json"
    if not _nonempty_file(manifest_path):
        raise Track1Error("Exomiser install manifest is absent")
    manifest = load_jsonish(manifest_path)
    if manifest.get("version") != version or manifest.get("data_version") != data_version:
        raise Track1Error("Exomiser install manifest version mismatch")
    expected = [
        f"exomiser-cli-{version}-distribution.zip",
        f"{data_version}_hg38.zip",
        f"{data_version}_phenotype.zip",
    ]
    archives = manifest.get("archives", [])
    if [record.get("file") for record in archives] != expected:
        raise Track1Error("Exomiser install manifest archive set mismatch")
    downloads = root / "downloads"
    if any(downloads.glob("*.part")):
        raise Track1Error("Exomiser partial archive remains")
    compacted = (root / "archive_compaction.json").is_file()
    if compacted:
        from mva_runner.maintenance import verify_installed_payload
        verify_installed_payload(root, check_hashes=check_hashes)
    for record in archives:
        archive = downloads / record["file"]
        if compacted and not archive.exists():
            # The installed-file hashes replace redundant download storage,
            # not scientific integrity. Original archive URLs/digests remain.
            continue
        if not _nonempty_file(archive) or archive.stat().st_size != int(record.get("size", -1)):
            raise Track1Error(f"Exomiser archive size mismatch: {archive.name}")
        if not _SHA256_RE.fullmatch(str(record.get("sha256", ""))):
            raise Track1Error(f"Exomiser archive checksum metadata is invalid: {archive.name}")
        if check_hashes and sha256_file(archive) != record["sha256"]:
            raise Track1Error(f"Exomiser archive checksum mismatch: {archive.name}")
    cli_root = root / f"exomiser-cli-{version}"
    if not _nonempty_file(cli_root / f"exomiser-cli-{version}.jar"):
        raise Track1Error("Exomiser CLI jar is missing or empty")
    for name in (f"{data_version}_hg38", f"{data_version}_phenotype"):
        data_dir = cli_root / "data" / name
        if not data_dir.is_dir() or not any(_nonempty_file(path) for path in data_dir.rglob("*")):
            raise Track1Error(f"Exomiser extracted data is missing or empty: {name}")


def _extract_zip_safely(archive: Path, destination: Path) -> None:
    destination_root = destination.resolve()
    try:
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                target = (destination / member.filename).resolve()
                if target != destination_root and destination_root not in target.parents:
                    raise Track1Error(
                        f"Refusing archive member outside destination: {member.filename}"
                    )
                if stat.S_ISLNK(member.external_attr >> 16):
                    raise Track1Error(
                        f"Refusing symbolic link in archive: {member.filename}"
                    )
            source.extractall(destination)
    except zipfile.BadZipFile as exc:
        raise Track1Error(f"Invalid Exomiser archive: {archive}") from exc


def download_reference(config_path: Path | str = DEFAULT_CONFIG) -> Path:
    cfg = load_jsonish(config_path)
    reference = cfg["reference"]
    fasta = PROJECT_ROOT / reference["fasta"]
    targets = {
        fasta: reference["fasta_url"],
        Path(str(fasta) + ".fai"): reference["fai_url"],
        fasta.with_suffix(".dict"): reference["dict_url"],
    }
    for destination, url in targets.items():
        if not destination.is_file() or destination.stat().st_size == 0:
            _download(url, destination)
    manifest = {}
    if RESOURCE_MANIFEST.exists():
        manifest = json.loads(RESOURCE_MANIFEST.read_text(encoding="utf-8"))
    manifest["reference"] = {
        "downloaded_at": utc_now(),
        "files": {
            str(path.relative_to(PROJECT_ROOT)): {
                "url": url,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path, url in targets.items()
        },
    }
    atomic_write_json(RESOURCE_MANIFEST, manifest, mode=0o644)
    return fasta


def install_exomiser(config_path: Path | str = DEFAULT_CONFIG) -> Path:
    cfg = load_jsonish(config_path)["annotation"]
    version = cfg["exomiser_version"]
    data_version = cfg["exomiser_data_version"]
    root = PROJECT_ROOT / cfg["exomiser_dir"]
    marker = root / ".complete"
    if marker.exists():
        try:
            verify_exomiser_install(config_path)
        except (Track1Error, OSError, ValueError, TypeError, KeyError):
            # Re-enter the idempotent install path so missing/corrupt sidecar
            # manifests cannot be hidden by a stale completion marker.
            pass
        else:
            return marker
    downloads = root / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    cli_filename = f"exomiser-cli-{version}-distribution.zip"
    data_base = cfg["exomiser_data_base_url"].rstrip("/")
    archives = [
        (cli_filename, cfg["exomiser_cli_url"], cfg.get("exomiser_cli_sha256"), root),
        (
            f"{data_version}_hg38.zip",
            f"{data_base}/{data_version}_hg38.zip",
            None,
            root / f"exomiser-cli-{version}" / "data",
        ),
        (
            f"{data_version}_phenotype.zip",
            f"{data_base}/{data_version}_phenotype.zip",
            None,
            root / f"exomiser-cli-{version}" / "data",
        ),
    ]
    records = []
    for filename, url, expected_sha256, destination in archives:
        archive = downloads / filename
        if not archive.exists():
            _download(url, archive)
        observed_sha256 = sha256_file(archive)
        if expected_sha256 and observed_sha256 != expected_sha256:
            archive.unlink()
            raise Track1Error(
                f"Checksum mismatch for {archive}: expected {expected_sha256}, "
                f"observed {observed_sha256}; corrupt archive removed"
            )
        destination.mkdir(parents=True, exist_ok=True)
        _extract_zip_safely(archive, destination)
        records.append(
            {
                "file": filename,
                "url": url,
                "sha256": observed_sha256,
                "size": archive.stat().st_size,
            }
        )
    # A genuine reinstall supersedes the compacted installation, not its
    # history. Keeping an active receipt bound to the old manifest would make
    # the repaired install fail verification forever. Archive only small
    # receipts; never duplicate the downloaded databases.
    for name in ("archive_compaction.json", "installed_payload.json"):
        old = root / name
        if old.is_file():
            history = root / "compaction_history"
            history.mkdir(exist_ok=True)
            old.replace(history / (sha256_file(old) + "_" + name))
    atomic_write_json(
        root / "install_manifest.json",
        {"installed_at": utc_now(), "version": version, "data_version": data_version, "archives": records},
        mode=0o644,
    )
    marker.write_text("complete\n", encoding="utf-8")
    return marker
