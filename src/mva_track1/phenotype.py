from __future__ import annotations

import csv
import io
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from .common import (
    PROJECT_ROOT,
    Track1Error,
    atomic_write_json,
    atomic_write_text,
    ensure_private_dir,
    load_jsonish,
)
from .vcf import inspect_vcf


HPO_PATTERN = re.compile(r"\bHP:\d{7}\b")
NEGATION_PATTERN = re.compile(
    r"\b(?:absent|denie[sd]?|lack(?:ed|ing|s)?|never|no|not|negative|without)\b",
    re.IGNORECASE,
)


def extract_docx_text(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            document = archive.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise Track1Error(f"Cannot read phenotype DOCX: {exc}") from exc
    root = ElementTree.fromstring(document)
    chunks: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}t") and node.text:
            chunks.append(node.text)
        elif node.tag.endswith("}p"):
            chunks.append("\n")
    return " ".join("".join(chunks).split())


def extract_hpo(docx: Path, output: Path, private_text: Path | None = None) -> list[dict[str, str]]:
    text = extract_docx_text(docx)
    found: dict[str, dict[str, str]] = {}
    for match in HPO_PATTERN.finditer(text):
        start = max(0, match.start() - 100)
        end = min(len(text), match.end() + 100)
        context = text[start:end].replace("\t", " ").replace("\n", " ")
        found.setdefault(
            match.group(),
            {"hpo_id": match.group(), "status": "REVIEW", "context": context},
        )

    ensure_private_dir(output.parent)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=["hpo_id", "status", "context"], delimiter="\t")
    writer.writeheader()
    writer.writerows(found.values())
    atomic_write_text(output, buffer.getvalue())
    if private_text is not None:
        atomic_write_text(private_text, text + "\n")
    return list(found.values())


def suggest_hpo_status(hpo_id: str, context: str) -> tuple[str, str]:
    location = context.find(hpo_id)
    if location < 0:
        return "REVIEW", "identifier_not_found_in_context"
    before = context[max(0, location - 80):location]
    after = context[location + len(hpo_id):location + len(hpo_id) + 40]
    if NEGATION_PATTERN.search(before) or NEGATION_PATTERN.search(after):
        return "LIKELY_ABSENT", "local_negation_cue"
    return "LIKELY_PRESENT", "no_local_negation_cue"


def write_proband_draft(
    vcf: Path,
    extracted: Path,
    output: Path,
    suggestions_output: Path,
) -> Path:
    info = inspect_vcf(vcf)
    if len(info["samples"]) != 1:
        raise Track1Error(
            "Automated phenotype draft requires a single-sample VCF; "
            "select the proband sample manually."
        )
    with extracted.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    suggestions: list[dict[str, str]] = []
    present: list[str] = []
    absent: list[str] = []
    for row in rows:
        status, reason = suggest_hpo_status(row["hpo_id"], row.get("context", ""))
        suggestions.append(
            {"hpo_id": row["hpo_id"], "suggested_status": status, "reason": reason}
        )
        if status == "LIKELY_ABSENT":
            absent.append(row["hpo_id"])
        elif status == "LIKELY_PRESENT":
            present.append(row["hpo_id"])

    suggestions_output.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=["hpo_id", "suggested_status", "reason"],
        delimiter="\t",
    )
    writer.writeheader()
    writer.writerows(suggestions)
    atomic_write_text(suggestions_output, buffer.getvalue())

    draft = {
        "proband_id": "PROBAND01",
        "vcf_sample_id": info["samples"][0],
        "sex": "UNKNOWN",
        "hpo_present": present or ["HP:0000000"],
        "hpo_absent": absent,
        "reviewed_by": "REPLACE_WITH_REVIEWER",
        "reviewed_at": "YYYY-MM-DD",
        "notes": (
            "AUTOMATED LOCAL DRAFT: verify every HPO suggestion against the "
            "private source text before copying to proband.local.yaml."
        ),
    }
    atomic_write_json(output, draft)
    return output


def validate_proband_config(path: Path) -> dict:
    if not path.is_file():
        raise Track1Error(
            "Missing config/proband.local.yaml. Copy the example and replace all placeholders."
        )
    cfg = load_jsonish(path)
    if cfg.get("proband_id") != "PROBAND01":
        raise Track1Error("proband_id must be PROBAND01")
    sample_id = str(cfg.get("vcf_sample_id", "")).strip()
    if not sample_id or "replace" in sample_id.casefold():
        raise Track1Error("vcf_sample_id has not been reviewed")
    reviewer = str(cfg.get("reviewed_by", "")).strip()
    if not reviewer or "replace" in reviewer.casefold():
        raise Track1Error("reviewed_by has not been completed")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(cfg.get("reviewed_at", ""))):
        raise Track1Error("reviewed_at must be an ISO date (YYYY-MM-DD)")
    present = cfg.get("hpo_present", [])
    absent = cfg.get("hpo_absent", [])
    if not present or "HP:0000000" in present:
        raise Track1Error("hpo_present is empty or still contains the placeholder")
    invalid = [term for term in [*present, *absent] if not HPO_PATTERN.fullmatch(term)]
    if invalid:
        raise Track1Error(f"Invalid HPO identifiers: {', '.join(invalid)}")
    if set(present) & set(absent):
        raise Track1Error("An HPO term cannot be both present and absent")
    return cfg
