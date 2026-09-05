import json
from pathlib import Path

import pytest

from mva_runner import bwa_provenance
from mva_track1.common import Track1Error, sha256_file


def fixture(root):
    reference = root / "resources/public/reference/synthetic.fasta"
    reference.parent.mkdir(parents=True)
    reference.write_text(">synthetic\nACGT\n")
    Path(f"{reference}.fai").write_text("synthetic\t4\t11\t4\t5\n")
    for suffix in bwa_provenance.SUFFIXES:
        Path(f"{reference}.{suffix}").write_bytes(b"synthetic-index")
    Path(f"{reference}.ann").write_text("4 1 11\n0 synthetic (null)\n0 4 0\n")
    files = {str(p.relative_to(root)): {"size": p.stat().st_size, "sha256": sha256_file(p)}
             for p in [reference, Path(f"{reference}.fai")]}
    (root / "resources/public/manifest.json").write_text(json.dumps({"reference": {"files": files}}))
    for name in ["bwa_index", "reads"]:
        definition = root / "workflow/envs" / f"{name}.yaml"
        definition.parent.mkdir(parents=True, exist_ok=True)
        definition.write_text(f"name: synthetic-{name}\n")
        prefix = root / ".conda/rules" / name
        (prefix / "bin").mkdir(parents=True)
        (prefix / "bin/bwa-mem2").write_bytes(b"synthetic-executable")
        (prefix / "conda-meta").mkdir()
        (prefix / "conda-meta/bwa.json").write_text(json.dumps({"name": "bwa-mem2", "version": "2.2.1"}))
        prefix.with_suffix(".yaml").write_bytes(definition.read_bytes())
        Path(f"{prefix}.env_setup_done").touch()
    return reference


def test_record_preserves_index_bytes_and_timestamps(tmp_path):
    reference = fixture(tmp_path)
    paths = [Path(f"{reference}.{suffix}") for suffix in bwa_provenance.SUFFIXES]
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}
    result = bwa_provenance.record(reference, tmp_path / "receipt.json", tmp_path)
    assert result["bwa_executables_identical"] and result["reference_contigs_verified"] == 1
    assert before == {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}


@pytest.mark.parametrize("failure", ["reference", "contig", "executable", "missing_index"])
def test_incompatible_or_incomplete_index_is_rejected_without_deleting_it(tmp_path, failure):
    reference = fixture(tmp_path)
    if failure == "reference": reference.write_text(">synthetic\nTGCA\n")
    if failure == "contig": Path(f"{reference}.ann").write_text("4 1 11\n0 different (null)\n0 4 0\n")
    if failure == "executable": (tmp_path / ".conda/rules/reads/bin/bwa-mem2").write_bytes(b"different-executable")
    if failure == "missing_index": Path(f"{reference}.pac").unlink()
    retained = Path(f"{reference}.0123")
    before = retained.read_bytes(), retained.stat().st_mtime_ns
    with pytest.raises(Track1Error):
        bwa_provenance.record(reference, tmp_path / "receipt.json", tmp_path)
    assert before == (retained.read_bytes(), retained.stat().st_mtime_ns)
    assert not (tmp_path / "receipt.json").exists()
