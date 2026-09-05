from mva_track2.analysis import validate_hypothesis
from mva_track2.evidence import abstracts, approved_applications


def test_search_or_label_alone_is_not_regulatory_approval():
    assert not approved_applications([{"products": [{"active_ingredients": [{"name": "SYNTHETIC"}]}]}], "synthetic")
    record = {"application_number": "NDA123456", "products": [{"active_ingredients": [{"name": "SYNTHETIC"}]}],
              "submissions": [{"submission_type": "ORIG", "submission_status": "AP"}]}
    assert approved_applications([record], "synthetic")[0]["jurisdiction"] == "United States FDA"
    assert not approved_applications([record], "different")


def test_abstract_parser_retains_public_id_and_study_type():
    xml = '<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123456</PMID><Article><ArticleTitle>Synthetic title</ArticleTitle><Abstract><AbstractText>Experimental evidence.</AbstractText></Abstract><PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'
    record = abstracts(xml)[0]
    assert record["id"] == "PMID:123456"
    assert record["publication_types"] == ["Journal Article"]


def test_unknown_mechanism_and_invented_evidence_cannot_pass():
    answer = {"decision": "retain", "candidate_id": "SYNTH", "variant_mechanism": "unknown", "variant_evidence": [],
              "supporting_evidence": [{"source_id": "invented", "quote": "unsupported claim"}],
              "conditional_mechanism": "conditional", "intervention_direction": "unknown", "opposing_evidence": "unknown",
              "safety_concerns": "unknown", "experiment": "test"}
    failures = validate_hypothesis(answer, {"SYNTH": {"consequence_1": "missense_variant"}}, {}, {})
    assert "variant_mechanism_unresolved" in failures
    assert "unverified_source_quote" in failures
    assert "no_verified_regulatory_approval" in failures
    answer["variant_mechanism"] = "predicted_loss_of_function"
    assert "loss_of_function_not_supported_by_supplied_consequence" in validate_hypothesis(answer, {"SYNTH": {"consequence_1": "missense_variant"}}, {}, {})
