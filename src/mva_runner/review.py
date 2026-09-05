"""Evidence-constrained local reviews; source text never leaves this machine.

HPO membership and verbatim source anchors are checked independently of the
model. Ambiguous, conflicting, or lexically unsupported assertions do not
become positive phenotype features merely because the model proposed them.
"""
from __future__ import annotations

import csv
import io
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, atomic_write_text, load_jsonish, sha256_file, utc_now
from mva_track1.download import SOURCE_DIR, verify_core
from mva_track1.phenotype import HPO_PATTERN, validate_proband_config
from mva_track1.resources import _download
from mva_track1.submission import _candidate_rows, reviewed_finalists
from mva_track1.vcf import inspect_vcf
from .local import MANIFEST, InterpretationError, infer

HPO_RELEASE = "v2026-09-01"
HPO_SHA256 = "93dace952fcb3ec4728818857f6ba76bc2d5312f4d83266519b8694b8e798f22"
HPO_PATH = PROJECT_ROOT / "resources/public/ontology/hp.obo"
NEGATED = re.compile(r"\b(no|not|without|absent|denied|negative for)\b", re.I)
UNCERTAIN = re.compile(r"\b(possible|possibly|suspected|uncertain|rule out|may have|might|family history)\b", re.I)


def normalise(text: str) -> str:
    return " " + " ".join(re.findall(r"[a-z0-9]+", text.lower())) + " "


def read_ontology(path: Path) -> tuple[dict, dict]:
    """Read active HPO names/synonyms and alternative-ID mappings from OBO."""
    terms, aliases = {}, {}
    for block in path.read_text().split("[Term]\n")[1:]:
        fields = defaultdict(list)
        for line in block.splitlines():
            if line.startswith("["):
                break
            if ": " in line:
                key, value = line.split(": ", 1)
                fields[key].append(value)
        identifier = next(iter(fields["id"]), "")
        if not HPO_PATTERN.fullmatch(identifier) or "true" in fields["is_obsolete"]:
            continue
        names = fields["name"] + [m.group(1) for s in fields["synonym"]
                                   if (m := re.match(r'"(.*?)"', s))]
        terms[identifier] = {"name": fields["name"][0], "names": names}
        aliases.update({alias: identifier for alias in fields["alt_id"]})
    if not terms:
        raise Track1Error("Pinned ontology has no active terms")
    return terms, aliases


def prepare_ontology() -> tuple[dict, dict]:
    if not HPO_PATH.exists():
        HPO_PATH.parent.mkdir(parents=True, exist_ok=True)
        _download(f"https://github.com/obophenotype/human-phenotype-ontology/releases/download/{HPO_RELEASE}/hp.obo", HPO_PATH)
    if sha256_file(HPO_PATH) != HPO_SHA256:
        raise Track1Error("Pinned HPO checksum mismatch")
    return read_ontology(HPO_PATH)


def paragraphs_from_docx(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = {}
    for node in root.iter():
        if node.tag.endswith("}p"):
            text = "".join(child.text or "" for child in node.iter() if child.tag.endswith("}t")).strip()
            if text:
                paragraphs[f"p{len(paragraphs) + 1:04d}"] = text
    if not paragraphs:
        raise InterpretationError("Phenotype document contains no readable paragraphs")
    return paragraphs


def validate_assertions(assertions: list[dict], paragraphs: dict, terms: dict, aliases: dict) -> tuple[dict, list]:
    """Collapse duplicate/conflicting assertions without silently inventing absence."""
    grouped, audit = defaultdict(set), []
    for assertion in assertions:
        identifier = aliases.get(assertion["hpo_id"], assertion["hpo_id"])
        quote = assertion["quote"].strip()
        paragraph = paragraphs.get(assertion["paragraph_id"], "")
        if identifier not in terms or len(quote) < 3 or quote not in paragraph:
            raise InterpretationError("Phenotype assertion lacks a valid ontology/source anchor")
        status = assertion["status"]
        if status not in {"present", "absent", "uncertain"}:
            raise InterpretationError("Unknown phenotype assertion status")
        # A verified quote alone does not prove that an arbitrary term matches
        # it. Retain unsupported semantic mappings for review, not Exomiser.
        lexical = (assertion["hpo_id"] in quote or identifier in quote or
                   any(normalise(name) in normalise(quote) for name in terms[identifier]["names"]))
        gate = "anchored"
        if not lexical:
            status, gate = "uncertain", "semantic_mapping_requires_review"
        elif UNCERTAIN.search(quote) or (status == "present" and NEGATED.search(quote)):
            status, gate = "uncertain", "qualified_or_negated_source"
        elif status == "absent" and not NEGATED.search(quote):
            status, gate = "uncertain", "absence_without_explicit_negation"
        grouped[identifier].add(status)
        audit.append({**assertion, "hpo_id": identifier, "validated_status": status, "gate": gate})
    result = {"present": [], "absent": [], "uncertain": []}
    for identifier, statuses in sorted(grouped.items()):
        status = next(iter(statuses)) if len(statuses) == 1 else "uncertain"
        result[status].append(identifier)
    return result, audit


def phenotype() -> None:
    verify_core()
    terms, aliases = prepare_ontology()
    docx = SOURCE_DIR / "Challenge_Clinical_Phenotype_1.docx"
    paragraphs = paragraphs_from_docx(docx)
    all_text = "\n".join(paragraphs.values())
    normal = normalise(all_text)
    explicit = {aliases.get(t, t) for t in HPO_PATTERN.findall(all_text)}
    suggestions = {identifier: value["name"] for identifier, value in terms.items()
                   if identifier in explicit or any(len(name) > 5 and normalise(name) in normal for name in value["names"])}
    schema = {"type": "object", "properties": {"assertions": {"type": "array", "maxItems": 160,
        "items": {"type": "object", "properties": {
            "hpo_id": {"type": "string"}, "status": {"enum": ["present", "absent", "uncertain"]},
            "paragraph_id": {"type": "string"}, "quote": {"type": "string"}, "reason": {"type": "string"}},
            "required": ["hpo_id", "status", "paragraph_id", "quote", "reason"], "additionalProperties": False}}},
        "required": ["assertions"], "additionalProperties": False}
    answer = infer((PROJECT_ROOT / "prompts/local/phenotype.md").read_text(),
                   json.dumps({"paragraphs": paragraphs, "ontology_suggestions": suggestions}), schema, "phenotype")
    features, audit = validate_assertions(answer["assertions"], paragraphs, terms, aliases)
    info = inspect_vcf(SOURCE_DIR / "WGS_EX2312012_HGWCNDSX7.vcf.gz")
    if len(info["samples"]) != 1:
        raise InterpretationError("Automated sample selection requires exactly one VCF sample")
    review = {"review_mode": "automated_local", "reviewed_at": utc_now(), "source_sha256": sha256_file(docx),
              "ontology_release": HPO_RELEASE, "ontology_sha256": HPO_SHA256,
              "model_manifest_sha256": sha256_file(MANIFEST), "features": features, "assertions": audit}
    atomic_write_json(PROJECT_ROOT / "work/private/phenotype_review.json", review)
    if not features["present"]:
        raise InterpretationError("No positive phenotype survived source/ontology validation; private review needed")
    cfg = {"proband_id": "PROBAND01", "vcf_sample_id": info["samples"][0], "sex": "UNKNOWN",
           "hpo_present": features["present"], "hpo_absent": features["absent"], "hpo_uncertain": features["uncertain"],
           "reviewed_by": "local-model:Qwen3-30B-A3B", "reviewed_at": utc_now()[:10], "review_mode": "automated_local",
           "notes": "Automated source-anchored research review; uncertain assertions excluded from phenotype scoring."}
    atomic_write_json(PROJECT_ROOT / "config/proband.local.yaml", cfg)
    validate_proband_config(PROJECT_ROOT / "config/proband.local.yaml")


def validate_selections(selections: list[dict], candidates: dict) -> None:
    ids = [item["candidate_id"] for item in selections]
    if not 1 <= len(ids) <= 10 or len(set(ids)) != len(ids) or any(i not in candidates for i in ids):
        raise InterpretationError("Finalists are not one to ten unique supplied candidates")
    for selection in selections:
        if not selection["rationale"].strip() or not selection["uncertainty"].strip():
            raise InterpretationError("Finalist lacks rationale or uncertainty")
        refs = selection["evidence"]
        if len({item["field"] for item in refs}) < 2:
            raise InterpretationError("Finalist requires two independent supplied evidence fields")
        for item in refs:
            if candidates[selection["candidate_id"]].get(item["field"]) != item["value"]:
                raise InterpretationError("Finalist evidence does not match the supplied record")


def infer_finalist_selections(system: str, payload: dict, schema: dict) -> tuple[dict, list[dict]]:
    """Allow at most three local reviews; never repair scientific values in code.

    A copied field can be real but belong to another candidate. Return the
    rejected response and validation reason to the local model for a fresh
    review of the original evidence. Every replacement must pass the unchanged
    exact-match gate. Retain rejected attempts privately and fail closed when
    the bounded review cannot satisfy it; do not retry an identical cached input.
    """
    candidates = {row["candidate_id"]: row for row in payload["candidates"]}
    attempts, feedback = [], None
    receipt = PROJECT_ROOT / "work/private/finalist_review_attempts.json"
    for attempt in range(1, 4):
        request = dict(payload)
        if feedback is not None:
            request["validation_feedback"] = feedback
        answer = None
        try:
            answer = infer(system, json.dumps(request), schema, "finalists")
            validate_selections(answer["selections"], candidates)
        except InterpretationError as exc:
            attempts.append({"attempt": attempt, "status": "rejected", "reason": str(exc)})
            atomic_write_json(receipt, {"review_mode": "automated_local", "attempts": attempts,
                                       "completed": False, "updated_at": utc_now()})
            feedback = {"attempt": attempt, "validation_error": str(exc), "previous_response": answer,
                "instruction": "Re-evaluate the original candidates. Each cited field and exact string value "
                "must belong to that selection's own candidate_id, not another record. Reconsider the "
                "selection, rationale and uncertainty together; do not preserve an unsupported conclusion. "
                "The original evidence and acceptance rules have not changed."}
            continue
        attempts.append({"attempt": attempt, "status": "accepted"})
        atomic_write_json(receipt, {"review_mode": "automated_local", "attempts": attempts,
                                   "completed": True, "updated_at": utc_now()})
        return answer, attempts
    raise InterpretationError("Finalist review failed evidence validation after three local attempts")


def finalists() -> None:
    candidate_path = PROJECT_ROOT / "results/private/candidates_ranked.tsv"
    all_candidates = _candidate_rows(candidate_path)
    shortlist = dict(list(all_candidates.items())[:40])
    # Add top genome-wide and historical candidates so the model sees the
    # effect of the known-gene prior. All selected IDs must still pass the new
    # evidence policy; excluded cis/same-locus historical pairs cannot return.
    baseline_path = candidate_path.with_name("candidates_baseline.tsv")
    if baseline_path.exists():
        for identifier in list(_candidate_rows(baseline_path))[:10]:
            if identifier in all_candidates:
                shortlist[identifier] = all_candidates[identifier]
    for identifier, candidate in all_candidates.items():
        if candidate["mva_gene_score"] == "0.000000":
            shortlist[identifier] = candidate
            if len(shortlist) >= 55:
                break
    schema = {"type": "object", "properties": {"selections": {"type": "array", "minItems": 1, "maxItems": 10,
        "items": {"type": "object", "properties": {
            "candidate_id": {"type": "string", "enum": list(shortlist)}, "finding_type": {"enum": ["primary", "secondary"]},
            "rationale": {"type": "string"}, "uncertainty": {"type": "string"},
            "evidence": {"type": "array", "minItems": 2, "items": {"type": "object",
                "properties": {"field": {"type": "string", "enum": sorted({field for row in shortlist.values() for field in row})},
                               "value": {"type": "string"}},
                "required": ["field", "value"], "additionalProperties": False}}},
            "required": ["candidate_id", "finding_type", "rationale", "uncertainty", "evidence"], "additionalProperties": False}}},
        "required": ["selections"], "additionalProperties": False}
    answer, attempts = infer_finalist_selections((PROJECT_ROOT / "prompts/local/finalists.md").read_text(),
        {"candidates": list(shortlist.values()), "phenotype": load_jsonish(PROJECT_ROOT / "config/proband.local.yaml")}, schema)
    output = io.StringIO()
    fields = ["candidate_id", "selected", "final_rank", "finding_type", "review_reason"]
    writer = csv.DictWriter(output, fields, delimiter="\t")
    writer.writeheader()
    for rank, item in enumerate(answer["selections"], 1):
        writer.writerow({"candidate_id": item["candidate_id"], "selected": "YES", "final_rank": rank,
                         "finding_type": item["finding_type"], "review_reason": "Automated local research review: " +
                         item["rationale"] + " Uncertainty: " + item["uncertainty"]})
    path = PROJECT_ROOT / "config/finalists.local.tsv"
    atomic_write_text(path, output.getvalue())
    # Keep the pre-read proposal immutable; measured re-review may shrink or
    # reorder the active shortlist without invalidating this upstream stage.
    atomic_write_text(PROJECT_ROOT / "work/private/finalists_proposed.tsv", output.getvalue())
    reviewed_finalists(path, candidate_path)
    atomic_write_json(PROJECT_ROOT / "work/private/finalist_review.json", {"review_mode": "automated_local",
        "reviewed_at": utc_now(), "candidates_sha256": sha256_file(candidate_path),
        "model_manifest_sha256": sha256_file(MANIFEST), "validation_attempts": attempts,
        "selections": answer["selections"]})


def reassess_reads() -> bool:
    """Remove contradicted hypotheses, retain ambiguity, and prefer measured support.

    No replacement is invented after seeing negative reads. A smaller honest
    submission is allowed. If every hypothesis is contradicted, stop with a
    recoverable scientific-review requirement instead of packaging a false hit.
    """
    candidates = PROJECT_ROOT / "results/private/candidates_ranked.tsv"
    path = PROJECT_ROOT / "config/finalists.local.tsv"
    selected = reviewed_finalists(path, candidates)
    validation_path = PROJECT_ROOT / "results/private/read_validation.tsv"
    with validation_path.open() as source:
        measured = {row["candidate_id"]: row for row in csv.DictReader(source, delimiter="\t")}
    excluded, retained = [], []
    for item in selected:
        record = measured.get(item["candidate_id"])
        if not record:
            raise InterpretationError("Finalist is missing measured read evidence")
        contradicted = record["pair_support"] == "unsupported" or record["phase_status"].endswith("_cis")
        (excluded if contradicted else retained).append(item)
    retained.sort(key=lambda row: (measured[row["candidate_id"]]["pair_support"] != "supported", int(row["final_rank"])))
    atomic_write_json(PROJECT_ROOT / "work/private/read_reassessment.json", {
        "review_mode": "automated_deterministic", "reviewed_at": utc_now(),
        "read_evidence_sha256": sha256_file(validation_path), "excluded": excluded,
        "retained_ids": [row["candidate_id"] for row in retained],
        "policy": "Exclude observed unsupported/cis; preserve unresolved or conflicting phase and ambiguous support."})
    if not retained:
        raise InterpretationError("All current finalists were contradicted by reads; scientific review is required")
    changed = [row["candidate_id"] for row in selected] != [row["candidate_id"] for row in retained]
    if changed:
        output = io.StringIO()
        writer = csv.DictWriter(output, ["candidate_id", "selected", "final_rank", "finding_type", "review_reason"], delimiter="\t")
        writer.writeheader()
        for rank, row in enumerate(retained, 1):
            writer.writerow({**row, "selected": "YES", "final_rank": rank})
        atomic_write_text(path, output.getvalue())
    return changed
