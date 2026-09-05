from __future__ import annotations

from types import SimpleNamespace

from mva_track1.validation import (
    _allele_observation,
    _phase_from_observations,
    _phase_from_whatshap,
    write_finalist_regions,
)


class FakeAlignment:
    def pileup(self, chrom, start, end, **kwargs):
        reads = []
        for index, base in enumerate(["G"] * 6 + ["A"] * 4):
            alignment = SimpleNamespace(
                is_unmapped=False,
                is_secondary=False,
                is_supplementary=False,
                is_duplicate=False,
                mapping_quality=60,
                query_qualities=[35],
                query_sequence=base,
                is_reverse=index % 2 == 1,
            )
            reads.append(
                SimpleNamespace(
                    alignment=alignment,
                    is_refskip=False,
                    query_position=0,
                    indel=0,
                )
            )
        return [SimpleNamespace(reference_pos=start, pileups=reads)]


def test_supported_snv_requires_depth_alt_count_and_both_strands() -> None:
    result = _allele_observation(
        FakeAlignment(), "chr15", 100, "A", "G",
        {
            "min_depth": 10,
            "min_alt_reads": 3,
            "min_mapping_quality": 20,
            "min_base_quality": 20,
        },
    )
    assert result["support"] == "supported"
    assert result["depth"] == 10
    assert result["alt_reads"] == 6
    assert result["vaf"] == 0.6


def test_read_linkage_can_support_trans_configuration() -> None:
    one = {
        "alt_fragments": {"a", "b"},
        "ref_fragments": {"c", "d"},
    }
    two = {
        "alt_fragments": {"c", "d"},
        "ref_fragments": {"a", "b"},
    }
    status, informative, cis, trans = _phase_from_observations(one, two, 2)
    assert status == "read_linkage_supports_trans"
    assert (informative, cis, trans) == (4, 0, 4)


def test_conflicting_read_linkage_is_not_overcalled() -> None:
    one = {
        "alt_fragments": {"cis", "trans"},
        "ref_fragments": set(),
    }
    two = {
        "alt_fragments": {"cis"},
        "ref_fragments": {"trans"},
    }
    status, informative, cis, trans = _phase_from_observations(one, two, 1)
    assert status == "conflicting_read_linkage"
    assert (informative, cis, trans) == (2, 1, 1)


def test_whatshap_requires_a_shared_phase_set() -> None:
    first = ("chr15", 100, "A", "G")
    second = ("chr15", 200, "C", "T")
    assert _phase_from_whatshap(
        {first: (1, "100"), second: (0, "100")}, first, second
    ) == ("whatshap_supports_trans", "100")
    assert _phase_from_whatshap(
        {first: (1, "100"), second: (0, "200")}, first, second
    ) is None


def test_finalist_region_spans_pair_and_intervening_variants(tmp_path) -> None:
    candidate_id = "BUB1B|chr15:100:A>G|chr15:300:C>T"
    candidates = tmp_path / "candidates.tsv"
    candidates.write_text(
        "candidate_id\tchrom_1\tpos_1\tchrom_2\tpos_2\n"
        f"{candidate_id}\tchr15\t100\tchr15\t300\n",
        encoding="utf-8",
    )
    finalists = tmp_path / "finalists.tsv"
    finalists.write_text(
        "candidate_id\tselected\tfinal_rank\tfinding_type\treview_reason\n"
        f"{candidate_id}\tYES\t1\tprimary\tReviewed synthetic candidate\n",
        encoding="utf-8",
    )
    output = tmp_path / "regions.tsv"
    write_finalist_regions(candidates, finalists, output)
    assert output.read_text(encoding="utf-8") == "chr15\t100\t300\n"
