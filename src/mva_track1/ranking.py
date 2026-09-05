from __future__ import annotations

import csv
import itertools
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .common import DEFAULT_CONFIG, Track1Error, load_jsonish
from .vcf import VariantRecord, iter_annotated_variants, with_exomiser


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    tier: str
    gene: str
    variant_1: VariantRecord
    variant_2: VariantRecord | None
    exomiser_score: float
    mva_gene_score: float
    inheritance_score: float
    effect_score: float
    rarity_score: float
    technical_score: float
    final_score: float
    phase_status: str = "unresolved"


OUTPUT_FIELDS = [
    "rank", "candidate_id", "tier", "gene",
    "chrom_1", "pos_1", "ref_1", "alt_1", "gt_1",
    "chrom_2", "pos_2", "ref_2", "alt_2", "gt_2",
    "consequence_1", "consequence_2", "max_af_1", "max_af_2",
    "transcript_1", "transcript_2", "hgvsc_1", "hgvsc_2", "hgvsp_1", "hgvsp_2",
    "clin_sig_1", "clin_sig_2", "exomiser_score", "mva_gene_score",
    "inheritance_score", "effect_score", "rarity_score", "technical_score",
    "final_score", "phase_status", "review_status", "review_reason",
]


def _variant_label(record: VariantRecord) -> str:
    return f"{record.chrom}:{record.pos}:{record.ref}>{record.alt}"


def _candidate_id(gene: str, first: VariantRecord, second: VariantRecord | None) -> str:
    labels = [_variant_label(first)]
    if second:
        labels.append(_variant_label(second))
    return f"{gene}|{'|'.join(sorted(labels))}"


def _pair_order(first: VariantRecord, second: VariantRecord) -> tuple[VariantRecord, VariantRecord]:
    def key(record: VariantRecord):
        chrom = record.chrom.removeprefix("chr")
        order = int(chrom) if chrom.isdigit() else {"X": 23, "Y": 24, "M": 25, "MT": 25}.get(chrom, 100)
        return order, record.pos, record.ref, record.alt

    return tuple(sorted((first, second), key=key))  # type: ignore[return-value]


def _load_exomiser_scores(path: Path | None) -> dict[tuple[str, int, str, str, str], float]:
    if path is None or not path.is_file():
        return {}
    scores: dict[tuple[str, int, str, str, str], float] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            upper = {key.upper(): value for key, value in row.items() if key}
            chrom = upper.get("CONTIG") or upper.get("CHROM") or upper.get("#CHROM")
            pos = upper.get("START") or upper.get("POS")
            ref = upper.get("REF")
            alt = upper.get("ALT")
            gene = upper.get("GENE_SYMBOL") or upper.get("GENE") or upper.get("SYMBOL")
            score_text = (
                upper.get("EXOMISER_GENE_COMBINED_SCORE")
                or upper.get("EXOMISER_VARIANT_SCORE")
                or upper.get("EXOMISER_SCORE")
                or upper.get("SCORE")
            )
            if not all((chrom, pos, ref, alt, gene, score_text)):
                continue
            try:
                score = float(score_text)
                if not math.isfinite(score) or score < 0:
                    continue
                key = (_canonical_chrom(chrom), int(pos), ref.upper(), alt.upper(), gene)
            except (TypeError, ValueError):
                continue
            scores[key] = max(scores.get(key, 0.0), score)
    maximum = max(scores.values(), default=1.0)
    if maximum > 1.0:
        scores = {key: value / maximum for key, value in scores.items()}
    return scores


def _canonical_chrom(chrom: str) -> str:
    """Exomiser may emit 1 while the supplied VCF uses chr1."""
    bare = str(chrom).removeprefix("chr")
    return "chr" + ("M" if bare == "MT" else bare)


def pair_phase(first: VariantRecord, second: VariantRecord) -> str:
    """Phase orientation is comparable only within a shared chromosome/block."""
    if (first.chrom == second.chrom and first.phase_set and first.phase_set == second.phase_set
            and "|" in first.genotype and "|" in second.genotype):
        orientation = "cis" if first.genotype == second.genotype else "trans"
        return f"input_phase_supports_{orientation}"
    return "unresolved"


def _score_candidate(
    first: VariantRecord,
    second: VariantRecord | None,
    known_mva: set[str],
    weights: dict[str, float],
    policy: str = "evidence",
) -> Candidate:
    variants = [first] + ([second] if second else [])
    # A strong allele cannot rescue an unsupported second allele in a recessive
    # hypothesis. Keep the historical arithmetic only for the baseline report.
    exomiser = (max if policy == "baseline" else min)(item.exomiser_score for item in variants)
    mva_gene = 1.0 if first.gene in known_mva else 0.0
    inheritance = 1.0 if second and first.is_het and second.is_het else (0.75 if first.is_hom_alt else 0.35)
    effect = (sum(item.effect_score for item in variants) / len(variants)
              if policy == "baseline" else min(item.effect_score for item in variants))
    rarity = sum(item.rarity_score for item in variants) / len(variants)
    technical = (sum(item.technical_score for item in variants) / len(variants)
                 if policy == "baseline" else min(item.technical_score for item in variants))
    values = {
        "exomiser": exomiser,
        "mva_gene": mva_gene,
        "inheritance": inheritance,
        "effect": effect,
        "rarity": rarity,
        "technical": technical,
    }
    final = sum(weights[key] * values[key] for key in weights)
    if second and mva_gene:
        tier = "A"
    elif second and exomiser >= 0.5:
        tier = "B"
    else:
        tier = "C"
    return Candidate(
        candidate_id=_candidate_id(first.gene, first, second),
        tier=tier,
        gene=first.gene,
        variant_1=first,
        variant_2=second,
        exomiser_score=exomiser,
        mva_gene_score=mva_gene,
        inheritance_score=inheritance,
        effect_score=effect,
        rarity_score=rarity,
        technical_score=technical,
        final_score=final,
        phase_status=pair_phase(first, second) if second else "not_applicable",
    )


def build_candidates(
    variants: Iterable[VariantRecord],
    known_mva: set[str],
    weights: dict[str, float],
    max_af: float,
    max_per_gene: int,
    policy: str = "evidence",
) -> list[Candidate]:
    by_gene: dict[str, dict[tuple[str, int, str, str], VariantRecord]] = {}
    for record in variants:
        if policy != "baseline" and record.gene == "UNANNOTATED":
            continue
        if record.max_af is not None and record.max_af > max_af:
            continue
        gene_records = by_gene.setdefault(record.gene, {})
        previous = gene_records.get(record.key)
        if previous is None or record.effect_score > previous.effect_score:
            gene_records[record.key] = record

    candidates: list[Candidate] = []
    for gene, keyed in by_gene.items():
        records = sorted(
            keyed.values(),
            key=lambda item: (item.exomiser_score, item.effect_score, item.rarity_score),
            reverse=True,
        )[:max_per_gene]
        het = [item for item in records if item.is_het]
        for first, second in itertools.combinations(het, 2):
            first, second = _pair_order(first, second)
            if policy != "baseline":
                same_locus = first.chrom == second.chrom and first.pos == second.pos
                same_source = bool(first.original_record and first.original_record == second.original_record)
                if same_locus or same_source or pair_phase(first, second).endswith("_cis"):
                    continue
            candidates.append(_score_candidate(first, second, known_mva, weights, policy))
        for record in records:
            if (record.is_hom_alt or (gene in known_mva and record.effect_score >= 0.75)
                    or (policy != "baseline" and record.effect_score >= 0.75 and record.exomiser_score >= 0.5)):
                candidates.append(_score_candidate(record, None, known_mva, weights, policy))

    tier_order = {"A": 0, "B": 1, "C": 2}
    candidates.sort(
        key=lambda item: (
            tier_order[item.tier] if policy == "baseline" else 0,
            -item.final_score,
            -item.exomiser_score,
            item.candidate_id,
        )
    )
    return candidates


def rank_vcf(
    vcf_path: Path,
    sample_id: str,
    output: Path,
    exomiser_tsv: Path | None = None,
    config_path: Path | str = DEFAULT_CONFIG,
) -> list[Candidate]:
    cfg = load_jsonish(config_path)
    scores = _load_exomiser_scores(exomiser_tsv)
    variants: list[VariantRecord] = []
    for record in iter_annotated_variants(vcf_path, sample_id):
        score = scores.get((_canonical_chrom(record.chrom), record.pos, record.ref, record.alt, record.gene), 0.0)
        variants.append(with_exomiser(record, score))
    if exomiser_tsv is not None and not any(item.exomiser_score > 0 for item in variants):
        raise Track1Error("No positive Exomiser scores joined to annotated alleles; inspect the local integration audit")
    candidates = build_candidates(
        variants,
        known_mva=set(cfg["project"]["known_mva_genes"]),
        weights=cfg["ranking"]["weights"],
        max_af=float(cfg["ranking"]["max_population_af"]),
        max_per_gene=int(cfg["ranking"]["max_variants_per_gene"]),
    )
    if not candidates:
        raise Track1Error("No candidate variants survived the configured ranking rules")
    write_candidates(candidates, output)
    # Preserve the previous policy as a reproducible comparison, not the default.
    baseline = build_candidates(variants, set(cfg["project"]["known_mva_genes"]),
        cfg["ranking"]["weights"], float(cfg["ranking"]["max_population_af"]),
        int(cfg["ranking"]["max_variants_per_gene"]), policy="baseline")
    write_candidates(baseline, output.with_name("candidates_baseline.tsv"))
    return candidates


def write_candidates(candidates: Iterable[Candidate], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS, delimiter="\t")
        writer.writeheader()
        for rank, candidate in enumerate(candidates, 1):
            one, two = candidate.variant_1, candidate.variant_2
            writer.writerow(
                {
                    "rank": rank,
                    "candidate_id": candidate.candidate_id,
                    "tier": candidate.tier,
                    "gene": candidate.gene,
                    "chrom_1": one.chrom,
                    "pos_1": one.pos,
                    "ref_1": one.ref,
                    "alt_1": one.alt,
                    "gt_1": one.genotype,
                    "chrom_2": two.chrom if two else "",
                    "pos_2": two.pos if two else "",
                    "ref_2": two.ref if two else "",
                    "alt_2": two.alt if two else "",
                    "gt_2": two.genotype if two else "",
                    "consequence_1": one.consequence,
                    "consequence_2": two.consequence if two else "",
                    "transcript_1": one.transcript,
                    "transcript_2": two.transcript if two else "",
                    "hgvsc_1": one.hgvsc,
                    "hgvsc_2": two.hgvsc if two else "",
                    "hgvsp_1": one.hgvsp,
                    "hgvsp_2": two.hgvsp if two else "",
                    "max_af_1": "" if one.max_af is None else one.max_af,
                    "max_af_2": "" if not two or two.max_af is None else two.max_af,
                    "clin_sig_1": one.clin_sig,
                    "clin_sig_2": two.clin_sig if two else "",
                    "exomiser_score": f"{candidate.exomiser_score:.6f}",
                    "mva_gene_score": f"{candidate.mva_gene_score:.6f}",
                    "inheritance_score": f"{candidate.inheritance_score:.6f}",
                    "effect_score": f"{candidate.effect_score:.6f}",
                    "rarity_score": f"{candidate.rarity_score:.6f}",
                    "technical_score": f"{candidate.technical_score:.6f}",
                    "final_score": f"{candidate.final_score:.6f}",
                    "phase_status": candidate.phase_status,
                    "review_status": "PENDING",
                    "review_reason": "",
                }
            )
