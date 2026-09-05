from __future__ import annotations

import csv
from pathlib import Path

from .common import utc_now


ACKNOWLEDGEMENT = (
    "This work was made possible through the Hackathon, organized by Sage "
    "Bionetworks in partnership with the MVA Society, Hugging Face, and BEACON "
    "(The Benchmarking, Evaluation, and Assessment Consortium for Science), "
    "with prize sponsorship from AWS and Anthropic. We are deeply grateful to "
    "the child and their family who generously contributed their data and their "
    "story to advance research into this rare disease. We acknowledge their "
    "trust in making this Hackathon possible."
)


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def generate_markdown(
    candidate_path: Path,
    finalist_path: Path,
    validation_path: Path | None,
    manifest_path: Path,
    output: Path,
    git_url: str,
) -> None:
    candidates = {row["candidate_id"]: row for row in _read_tsv(candidate_path)}
    finalists = [
        row for row in _read_tsv(finalist_path)
        if row.get("selected", "").upper() in {"YES", "Y", "TRUE", "1"}
    ]
    finalists.sort(key=lambda row: int(row["final_rank"]))
    validation = {row["candidate_id"]: row for row in _read_tsv(validation_path)} if validation_path else {}
    lines = [
        "# Track 1 Variant-Prioritisation Report",
        "",
        f"Generated: {utc_now()}",
        "",
        "## Scope and interpretation",
        "",
        "This report prioritises research candidates for PROBAND01. It is not a clinical diagnosis,",
        "medical recommendation, or substitute for review by an accredited clinical genetics service.",
        "",
        "## Reproducibility",
        "",
        f"- Public workflow repository: {git_url}",
        f"- Private input/run manifest: `{manifest_path}`",
        "- Assembly: GRCh38; normalized alleles are reported using `chr*` coordinates.",
        "- Patient-level analysis was performed locally; no gated records were sent to hosted APIs.",
        "- EPCR values are monotonic ranking values and are not clinically calibrated probabilities.",
        "",
        "## Method",
        "",
        "The supplied VCF was integrity-checked, reference-validated, left-normalized, split to",
        "biallelic records, annotated offline with Ensembl VEP, and prioritised with the Exomiser",
        "exome preset using reviewed HPO terms. Same-gene heterozygous pairs were ranked through a prespecified",
        "compound-heterozygous model combining phenotype, established MVA association, inheritance,",
        "functional effect, population rarity, and technical genotype quality. Disease-aware and",
        "genome-wide lanes were retained to reduce gene-panel anchoring.",
        "",
        "## Ranked candidates",
        "",
    ]
    for reviewed in finalists:
        candidate = candidates[reviewed["candidate_id"]]
        first = f"{candidate['chrom_1']}:{candidate['pos_1']} {candidate['ref_1']}>{candidate['alt_1']}"
        second = ""
        if candidate["chrom_2"]:
            second = f"{candidate['chrom_2']}:{candidate['pos_2']} {candidate['ref_2']}>{candidate['alt_2']}"
        validation_row = validation.get(reviewed["candidate_id"], {})
        support = validation_row.get("pair_support", "not_raw_validated")
        phase = validation_row.get("phase_status", "not_raw_validated")
        rationale = reviewed["review_reason"].replace("|", "\\|")
        lines.extend([
            f"### Rank {reviewed['final_rank']}: {candidate['gene']}", "",
            f"Variant 1: {first}." + (f" Variant 2: {second}." if second else " Single-variant hypothesis."), "",
            f"Research score: {float(candidate['final_score']):.4f}; descriptive tier: {candidate['tier']}.", "",
            f"Measured read support: {support}. Phase: {phase}.", "", rationale.replace('\\|', '|'), "",
        ])
    lines.extend(
        [
            "",
            "## Raw-read validation",
            "",
            "Finalists were evaluated for depth, alternate-read count, allele balance, mapping/base",
            "quality, strand support, and read-backed phase where possible. Lack of read-backed phase",
            "does not establish that two variants are in trans; parental or orthogonal testing would be required.",
            "",
            "## Limitations",
            "",
            "The initial workflow does not perform an independent whole-genome small-variant, CNV, or",
            "structural-variant call. Population and pathogenicity annotations are versioned snapshots,",
            "and automated predictions are evidence rather than clinical classifications.",
            "",
            "## Required acknowledgement",
            "",
            ACKNOWLEDGEMENT,
            "",
        ]
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def markdown_to_pdf(markdown_path: Path, pdf_path: Path) -> None:
    # Shared renderer keeps candidate cards and citations legible on A4 pages.
    from mva_runner.render import markdown_to_pdf as render
    render(markdown_path, pdf_path)
