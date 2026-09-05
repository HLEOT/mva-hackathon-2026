from __future__ import annotations

from mva_track1.common import load_jsonish


def test_dataset_inventory_is_complete_and_unique() -> None:
    config = load_jsonish()
    core = config["huggingface"]["core_files"]
    fastqs = config["huggingface"]["fastq_files"]
    assert len(core) == 3
    assert len(fastqs) == 8
    assert len(set(fastqs)) == 8
    assert sum("_R1_" in item for item in fastqs) == 4
    assert sum("_R2_" in item for item in fastqs) == 4


def test_ranking_weights_sum_to_one() -> None:
    weights = load_jsonish()["ranking"]["weights"]
    assert abs(sum(weights.values()) - 1.0) < 1e-9


def test_exomiser_release_and_data_are_compatible() -> None:
    annotation = load_jsonish()["annotation"]
    assert annotation["exomiser_version"] == "15.1.0"
    assert annotation["exomiser_data_version"] == "2602"
    assert annotation["exomiser_preset"] == "exome"
