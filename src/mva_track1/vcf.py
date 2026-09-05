from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

from .common import Track1Error


CSQ_FORMAT = re.compile(r"Format:\s*([^\"]+)")
SEVERITY = {"HIGH": 1.0, "MODERATE": 0.75, "LOW": 0.35, "MODIFIER": 0.10}
EXPLICIT_POPULATION_AF_FIELDS = (
    "MAX_AF",
    "gnomAD_AF",
    "gnomADe_AF",
    "gnomADg_AF",
)


@dataclass(frozen=True)
class VariantRecord:
    chrom: str
    pos: int
    ref: str
    alt: str
    gene: str
    genotype: str
    gq: float | None
    dp: float | None
    consequence: str
    impact: str
    max_af: float | None
    clin_sig: str
    exomiser_score: float = 0.0
    phase_set: str = ""
    original_record: str = ""
    transcript: str = ""
    hgvsc: str = ""
    hgvsp: str = ""

    @property
    def key(self) -> tuple[str, int, str, str]:
        return self.chrom, self.pos, self.ref, self.alt

    @property
    def is_het(self) -> bool:
        alleles = re.split(r"[/|]", self.genotype)
        return len(alleles) == 2 and sorted(alleles) == ["0", "1"]

    @property
    def is_hom_alt(self) -> bool:
        return self.genotype in {"1/1", "1|1"}

    @property
    def effect_score(self) -> float:
        score = SEVERITY.get(self.impact.upper(), 0.1)
        clinical = self.clin_sig.lower()
        if "pathogenic" in clinical and "conflict" not in clinical:
            score = max(score, 1.0)
        elif "benign" in clinical and "conflict" not in clinical:
            score = min(score, 0.05)
        return score

    @property
    def rarity_score(self) -> float:
        if self.max_af is None:
            return 0.5
        if self.max_af <= 0:
            return 1.0
        import math

        return min(1.0, max(0.0, -math.log10(self.max_af) / 6.0))

    @property
    def technical_score(self) -> float:
        gq = 0.5 if self.gq is None else min(1.0, max(0.0, self.gq / 60.0))
        dp = 0.5 if self.dp is None else min(1.0, max(0.0, self.dp / 30.0))
        return (gq + dp) / 2.0


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def _parse_info(text: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for item in text.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            parsed[key] = value
        elif item:
            parsed[item] = "true"
    return parsed


def _float_or_none(value: str | None) -> float | None:
    if not value or value in {".", "-"}:
        return None
    values: list[float] = []
    for part in re.split(r"[,&]", value):
        try:
            values.append(float(part))
        except ValueError:
            continue
    return max(values) if values else None


def _explicit_population_af(values: dict[str, str]) -> float | None:
    frequencies = [
        frequency
        for field in EXPLICIT_POPULATION_AF_FIELDS
        if (frequency := _float_or_none(values.get(field))) is not None
    ]
    return max(frequencies) if frequencies else None


def _minimal_alt_allele(ref: str, alt: str) -> str:
    """Return VEP's minimal alternate allele representation for a VCF allele."""
    minimal_ref = ref.upper()
    minimal_alt = alt.upper()
    if alt.startswith("<") and alt.endswith(">"):
        return alt[1:-1].upper()
    while minimal_ref and minimal_alt and minimal_ref[-1] == minimal_alt[-1]:
        minimal_ref = minimal_ref[:-1]
        minimal_alt = minimal_alt[:-1]
    while minimal_ref and minimal_alt and minimal_ref[0] == minimal_alt[0]:
        minimal_ref = minimal_ref[1:]
        minimal_alt = minimal_alt[1:]
    return minimal_alt or "-"


def _csq_matches_biallelic_alt(csq: dict[str, str], ref: str, alt: str) -> bool:
    allele_number = (csq.get("ALLELE_NUM") or "").strip()
    if allele_number not in {"", ".", "-"}:
        try:
            return int(allele_number) == 1
        except ValueError:
            return False

    allele = (csq.get("Allele") or "").strip().upper()
    if not allele or allele == ".":
        return True
    alt_upper = alt.upper()
    candidates = {alt_upper, _minimal_alt_allele(ref, alt)}
    if alt.startswith("<") and alt.endswith(">"):
        candidates.add(alt[1:-1].upper())
    return allele in candidates


def inspect_vcf(path: Path) -> dict:
    samples: list[str] = []
    reference = ""
    contigs: dict[str, int | None] = {}
    with _open_text(path) as handle:
        for line in handle:
            if line.startswith("##reference="):
                reference = line.strip().split("=", 1)[1]
            elif line.startswith("##contig=<"):
                body = line.strip()[10:-1]
                attrs = _parse_info(body.replace(",", ";"))
                length = attrs.get("length")
                contigs[attrs.get("ID", "")] = int(length) if length and length.isdigit() else None
            elif line.startswith("#CHROM"):
                fields = line.rstrip("\n").split("\t")
                samples = fields[9:]
                break
    if not samples:
        raise Track1Error(f"VCF has no sample columns: {path}")
    return {"samples": samples, "reference": reference, "contigs": contigs}


def iter_annotated_variants(path: Path, sample_id: str) -> Iterator[VariantRecord]:
    csq_fields: list[str] = []
    sample_index: int | None = None
    with _open_text(path) as handle:
        for line in handle:
            if line.startswith("##INFO=<ID=CSQ"):
                match = CSQ_FORMAT.search(line)
                if match:
                    csq_fields = match.group(1).rstrip("> ").split("|")
            elif line.startswith("#CHROM"):
                header = line.rstrip("\n").split("\t")
                if sample_id not in header[9:]:
                    raise Track1Error(
                        f"Configured sample {sample_id!r} not found; VCF samples: {', '.join(header[9:])}"
                    )
                sample_index = header.index(sample_id)
            elif line.startswith("#"):
                continue
            else:
                if sample_index is None:
                    raise Track1Error("VCF #CHROM header is missing")
                fields = line.rstrip("\n").split("\t")
                if len(fields) <= sample_index:
                    continue
                chrom, pos, _vid, ref, alt_text, _qual, _flt, info_text, fmt = fields[:9]
                alts = alt_text.split(",")
                if len(alts) != 1:
                    raise Track1Error("Candidate parser requires a normalized biallelic VCF")
                alt = alts[0]
                if _flt not in {"PASS", "."}:
                    continue
                fmt_keys = fmt.split(":")
                sample_values = fields[sample_index].split(":")
                sample = dict(zip(fmt_keys, sample_values))
                gt = sample.get("GT", "./.")
                if "1" not in re.split(r"[/|]", gt):
                    continue
                info = _parse_info(info_text)
                max_af = _explicit_population_af(info)
                annotations: dict[str, tuple[str, str, str, str, float | None, str, str]] = {}
                if csq_fields and info.get("CSQ"):
                    for raw in info["CSQ"].split(","):
                        values = raw.split("|")
                        csq = dict(zip(csq_fields, values))
                        if not _csq_matches_biallelic_alt(csq, ref, alt):
                            continue
                        gene = csq.get("SYMBOL") or csq.get("Gene") or ""
                        if not gene:
                            continue
                        consequence = csq.get("Consequence", "")
                        impact = csq.get("IMPACT", "MODIFIER")
                        clin_sig = csq.get("CLIN_SIG", "")
                        transcript_af = _explicit_population_af(csq)
                        existing = annotations.get(gene)
                        if existing is None or SEVERITY.get(impact, 0.0) > SEVERITY.get(existing[1], 0.0):
                            annotations[gene] = (
                                consequence,
                                impact,
                                clin_sig,
                                csq.get("Feature", ""),
                                transcript_af,
                                unquote(csq.get("HGVSc", "")),
                                unquote(csq.get("HGVSp", "")),
                            )
                if not annotations:
                    gene = info.get("SYMBOL") or info.get("GENE") or "UNANNOTATED"
                    annotations[gene] = (
                        info.get("Consequence", ""),
                        info.get("IMPACT", "MODIFIER"),
                        info.get("CLNSIG", ""),
                        "",
                        None,
                        "",
                        "",
                    )
                for gene, annotation in annotations.items():
                    consequence, impact, clin_sig, feature, transcript_af, hgvsc, hgvsp = annotation
                    af_values = [value for value in (max_af, transcript_af) if value is not None]
                    yield VariantRecord(
                        chrom=chrom,
                        pos=int(pos),
                        ref=ref.upper(),
                        alt=alt.upper(),
                        gene=gene,
                        genotype=gt,
                        gq=_float_or_none(sample.get("GQ")),
                        dp=_float_or_none(sample.get("DP")),
                        consequence=consequence,
                        impact=impact,
                        max_af=max(af_values) if af_values else None,
                        clin_sig=clin_sig,
                        phase_set=sample.get("PS", "") if sample.get("PS") != "." else "",
                        original_record=info.get("ORIGINAL_RECORD", ""),
                        # Keep identifiers from the same allele/transcript as
                        # the selected consequence. HGVS is notation, not a
                        # claim that this variant's functional effect is known.
                        transcript=feature,
                        hgvsc=hgvsc,
                        hgvsp=hgvsp,
                    )


def with_exomiser(record: VariantRecord, score: float) -> VariantRecord:
    return replace(record, exomiser_score=max(0.0, min(1.0, score)))
