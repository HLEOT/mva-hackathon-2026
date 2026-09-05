"""All alleles, genes, assays and source quotations in this module are synthetic."""
from copy import deepcopy

import jsonschema
import pytest

from mva_track2.analysis import FUNCTIONAL_MECHANISMS, _schema, evidence_index, hgvs_mentioned, validate_hypothesis


def example(mechanism="literature_supported_gain_of_function"):
    effect = {"literature_supported_gain_of_function": "increased activity",
              "literature_supported_loss_of_function": "reduced activity",
              "literature_supported_dominant_negative": "suppression of coexpressed wild-type activity"}[mechanism]
    quote = f"SYNTHETIC R12H showed {effect} in the controlled synthetic assay."
    source = {"PMID:SYNTHETIC": {"text": quote, "kind": "literature", "primary": True}}
    candidate = {"gene": "SYNTHETIC", "consequence_1": "missense_variant", "hgvsp_1": "ENSP_SYNTHETIC.1:p.Arg12His"}
    answer = {"decision": "retain", "candidate_id": "SYNTH", "variant_mechanism": mechanism,
              "variant_evidence": [{"field": "gene", "value": "SYNTHETIC"}, {"field": "consequence_1", "value": "missense_variant"}],
              "supporting_evidence": [{"source_id": "PMID:SYNTHETIC", "quote": quote, "interpretation": "Conditional functional support", "evidence_type": "direct_experiment"}],
              "functional_variant_evidence": [{"identifier_field": "hgvsp_1", "source_id": "PMID:SYNTHETIC", "quote": quote,
                  "assay": "Synthetic controlled assay", "observed_effect": effect, "reference_context": "Protein change matches; isoform remains conditional",
                  "limitations": "The assay is not a patient-level or therapeutic validation"}],
              "conditional_mechanism": "Conditional chain", "intervention_direction": "Test reversal of the measured defect",
              "rationale": "Synthetic example", "opposing_evidence": "Alternative mechanism remains possible",
              "safety_concerns": "Assay toxicity must be measured", "experiment": "Test rescue with controls",
              "limitations": ["Research only", "Isoform and cellular context require confirmation"]}
    drug = {"approval": [{"jurisdiction": "synthetic"}], "labels": [{}], "compounds": [{"max_phase": 4}]}
    return answer, {"SYNTH": candidate}, drug, source


@pytest.mark.parametrize("mechanism", sorted(FUNCTIONAL_MECHANISMS))
def test_functional_mechanisms_have_an_explicit_allele_linked_path(mechanism):
    data = example(mechanism)
    jsonschema.validate(data[0], _schema())
    assert validate_hypothesis(*data) == []


@pytest.mark.parametrize("change,expected", [
    ("wrong_allele", "functional_evidence_does_not_identify_supplied_allele"),
    ("other_gene", "functional_evidence_gene_not_identified"),
    ("review", "functional_evidence_is_not_primary_literature"),
    ("invented_quote", "unverified_functional_source_quote"),
    ("missing_assay", "functional_assay_or_reference_context_missing"),
    ("pathway_only", "functional_evidence_missing_from_direct_claims"),
])
def test_functional_claims_cannot_bypass_identity_source_or_assay_gates(change, expected):
    answer, candidates, drug, sources = example()
    if change == "wrong_allele":
        candidates["SYNTH"]["hgvsp_1"] = "ENSP_SYNTHETIC.1:p.Arg112His"
    elif change == "other_gene":
        candidates["SYNTH"]["gene"] = "OTHER"
    elif change == "review":
        sources["PMID:SYNTHETIC"]["primary"] = False
    elif change == "invented_quote":
        answer["functional_variant_evidence"][0]["quote"] = "Invented functional evidence"
    elif change == "missing_assay":
        answer["functional_variant_evidence"][0]["assay"] = ""
    elif change == "pathway_only":
        answer["supporting_evidence"][0]["evidence_type"] = "pathway_inference"
    assert expected in validate_hypothesis(answer, candidates, drug, sources)


def test_gene_knockout_does_not_characterise_a_specific_missense_allele():
    answer, candidates, drug, sources = example()
    sources["PMID:SYNTHETIC"]["text"] = "SYNTHETIC knockout reduced activity."
    answer["functional_variant_evidence"][0]["quote"] = sources["PMID:SYNTHETIC"]["text"]
    answer["supporting_evidence"][0]["quote"] = sources["PMID:SYNTHETIC"]["text"]
    assert "functional_evidence_does_not_identify_supplied_allele" in validate_hypothesis(answer, candidates, drug, sources)


def test_hgvs_matching_is_bounded_and_does_not_guess_unknown_changes():
    assert hgvs_mentioned("ENSP_SYNTHETIC.1:p.Arg12His", "SYNTHETIC R12H increased activity.")
    assert hgvs_mentioned("ENSP_SYNTHETIC.1:p.Arg12His", "SYNTHETIC p.Arg12His increased activity.")
    assert not hgvs_mentioned("ENSP_SYNTHETIC.1:p.Arg12His", "SYNTHETIC R112H increased activity.")
    assert not hgvs_mentioned("ENSP_SYNTHETIC.1:p.?", "SYNTHETIC p.? has an unknown effect.")


@pytest.mark.parametrize("types", [[], ["Review"], ["Systematic Review"], ["Meta-Analysis"], ["Editorial"]])
def test_missing_or_secondary_publication_type_is_not_primary_evidence(types):
    corpus = {"literature": [{"id": "synthetic", "title": "Synthetic", "abstract": "Example", "url": "https://example.test", "publication_types": types}],
              "drugs": {"synthetic": {"compounds": [], "labels": []}}}
    assert not evidence_index(corpus, "synthetic")["synthetic"]["primary"]
