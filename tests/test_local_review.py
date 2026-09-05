"""Synthetic clinical assertions only: no real patient fixtures in this tree."""
import pytest

from mva_runner.local import InterpretationError
from mva_runner.review import validate_assertions, validate_selections
from mva_runner.scientific import alignment_threads

TERMS = {"HP:0000252": {"name": "Microcephaly", "names": ["Microcephaly"]}}


def assertion(status="present", quote="Microcephaly", **extra):
    return {"hpo_id": "HP:0000252", "status": status, "quote": quote, "paragraph_id": "p0001", "reason": "synthetic", **extra}


def test_positive_requires_ontology_and_exact_source():
    result, audit = validate_assertions([assertion()], {"p0001": "Microcephaly."}, TERMS, {})
    assert result["present"] == ["HP:0000252"]
    with pytest.raises(InterpretationError):
        validate_assertions([assertion(quote="Invented microcephaly")], {"p0001": "Microcephaly."}, TERMS, {})
    with pytest.raises(InterpretationError):
        validate_assertions([assertion(hpo_id="HP:9999999")], {"p0001": "Microcephaly."}, TERMS, {})


def test_negated_possible_and_conflicting_assertions_stay_uncertain():
    for text in ("No microcephaly", "Possible microcephaly"):
        result, _ = validate_assertions([assertion(quote=text)], {"p0001": text}, TERMS, {})
        assert result["uncertain"] == ["HP:0000252"]
    result, _ = validate_assertions([assertion(), assertion("absent", "No microcephaly", paragraph_id="p0002")],
                                  {"p0001": "Microcephaly.", "p0002": "No microcephaly"}, TERMS, {})
    assert result["uncertain"] == ["HP:0000252"]


def test_absence_is_not_inferred_from_a_positive_quote():
    result, _ = validate_assertions([assertion("absent")], {"p0001": "Microcephaly"}, TERMS, {})
    assert not result["absent"]


def test_unrelated_but_real_quote_does_not_prove_semantic_mapping():
    result, _ = validate_assertions([assertion(quote="Height was measured")], {"p0001": "Height was measured"}, TERMS, {})
    assert not result["present"]


def test_finalist_rejects_invented_field_value():
    candidates = {"synthetic": {"gene": "SYNTH", "phase_status": "unresolved"}}
    selection = {"candidate_id": "synthetic", "rationale": "Hypothesis", "uncertainty": "Phase unresolved",
                 "evidence": [{"field": "gene", "value": "SYNTH"}, {"field": "phase_status", "value": "trans"}]}
    with pytest.raises(InterpretationError):
        validate_selections([selection], candidates)


@pytest.mark.parametrize("cpus", [16, 32, 64, 96, 112])
def test_all_alignment_workers_fit_allocated_cpu_budget(cpus):
    assert alignment_threads(cpus)["accounted_cpus"] <= cpus
