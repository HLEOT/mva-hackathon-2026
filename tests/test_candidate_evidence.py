from dataclasses import replace

from mva_track1.ranking import build_candidates, pair_phase
from mva_track1.vcf import VariantRecord

WEIGHTS = {"exomiser":0.45,"mva_gene":0.2,"inheritance":0.15,"effect":0.1,"rarity":0.05,"technical":0.05}


def variant(pos, **changes):
    return replace(VariantRecord("chr1",pos,"A","G","SYNTHETIC","0/1",60,30,
        "missense_variant","MODERATE",0.000001,"",0.9), **changes)


def test_shared_phase_block_cis_pair_is_excluded():
    a = variant(100, genotype="0|1", phase_set="99")
    b = variant(200, genotype="0|1", phase_set="99")
    assert pair_phase(a,b) == "input_phase_supports_cis"
    result = build_candidates([a,b],set(),WEIGHTS,0.01,50)
    assert not any(c.variant_2 for c in result)


def test_phase_from_different_blocks_remains_unresolved():
    assert pair_phase(variant(100,genotype="0|1",phase_set="1"),
                      variant(200,genotype="1|0",phase_set="2")) == "unresolved"


def test_same_locus_does_not_become_a_spurious_pair():
    result = build_candidates([variant(100),variant(100,alt="T")],set(),WEIGHTS,0.01,50)
    assert not any(c.variant_2 for c in result)


def test_weak_second_allele_is_not_rescued_by_strong_first():
    result = build_candidates([variant(100),variant(200,exomiser_score=0.01,impact="MODIFIER")],set(),WEIGHTS,0.01,50)
    pair = next(c for c in result if c.variant_2)
    assert pair.exomiser_score == 0.01
    assert pair.effect_score == 0.1


def test_strong_genomewide_pair_can_outrank_known_gene_pair():
    variants = [variant(100,gene="KNOWN",exomiser_score=0.01),variant(200,gene="KNOWN",exomiser_score=0.01),
                variant(300,exomiser_score=1),variant(400,exomiser_score=1)]
    result = build_candidates(variants,{"KNOWN"},WEIGHTS,0.01,50)
    assert result[0].gene == "SYNTHETIC"


def test_candidate_table_preserves_hgvs_for_local_evidence_linking(tmp_path):
    import csv
    from mva_track1.ranking import write_candidates
    record = variant(100, genotype="1/1", transcript="ENST_SYNTHETIC.1",
                     hgvsc="ENST_SYNTHETIC.1:c.35A>G", hgvsp="ENSP_SYNTHETIC.1:p.Arg12His")
    candidates = build_candidates([record], set(), WEIGHTS, 0.01, 50)
    path = tmp_path / "candidates.tsv"
    write_candidates(candidates, path)
    with path.open() as handle:
        row, = csv.DictReader(handle, delimiter="\t")
    assert row["transcript_1"] == record.transcript
    assert row["hgvsc_1"] == record.hgvsc
    assert row["hgvsp_1"] == record.hgvsp
    assert not row["hgvsp_2"]
