from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

from .artifacts import READ_VALIDATION_FIELDS
from .common import DEFAULT_CONFIG, Track1Error, load_jsonish
from .submission import reviewed_finalists


def write_finalist_regions(
    candidates_path: Path,
    finalists_path: Path,
    output: Path,
) -> None:
    with candidates_path.open(encoding="utf-8", newline="") as handle:
        candidates = {
            row["candidate_id"]: row
            for row in csv.DictReader(handle, delimiter="\t")
        }
    selected = reviewed_finalists(finalists_path, candidates_path)
    intervals: set[tuple[str, int, int]] = set()
    for reviewed in selected:
        candidate_id = reviewed["candidate_id"]
        if candidate_id not in candidates:
            raise Track1Error(f"Reviewed finalist no longer exists: {candidate_id}")
        candidate = candidates[candidate_id]
        chrom_one, pos_one = candidate["chrom_1"], int(candidate["pos_1"])
        if candidate.get("chrom_2") and candidate["chrom_2"] == chrom_one:
            pos_two = int(candidate["pos_2"])
            intervals.add((chrom_one, min(pos_one, pos_two), max(pos_one, pos_two)))
        else:
            intervals.add((chrom_one, pos_one, pos_one))
            if candidate.get("chrom_2"):
                pos_two = int(candidate["pos_2"])
                intervals.add((candidate["chrom_2"], pos_two, pos_two))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        for chrom, start, end in sorted(intervals):
            handle.write(f"{chrom}\t{start}\t{end}\n")


def _allele_observation(alignment: Any, chrom: str, pos: int, ref: str, alt: str, cfg: dict) -> dict[str, Any]:
    min_mq = int(cfg["min_mapping_quality"])
    min_bq = int(cfg["min_base_quality"])
    depth = alt_count = ref_count = forward = reverse = 0
    mapqs: list[int] = []
    baseqs: list[int] = []
    alt_fragments: set[str] = set()
    ref_fragments: set[str] = set()
    try:
        columns = alignment.pileup(chrom, pos - 1, pos, truncate=True, stepper="samtools", min_base_quality=0)
        for column in columns:
            if column.reference_pos != pos - 1:
                continue
            for pileup_read in column.pileups:
                read = pileup_read.alignment
                if read.is_unmapped or read.is_secondary or read.is_supplementary or read.is_duplicate:
                    continue
                if read.mapping_quality < min_mq or pileup_read.is_refskip:
                    continue
                query_pos = pileup_read.query_position
                if query_pos is None:
                    continue
                qualities = read.query_qualities or []
                base_quality = qualities[query_pos] if query_pos < len(qualities) else 0
                if base_quality < min_bq:
                    continue
                depth += 1
                mapqs.append(read.mapping_quality)
                baseqs.append(base_quality)
                supports_alt = False
                supports_ref = False
                if len(ref) == len(alt) == 1:
                    base = read.query_sequence[query_pos].upper()
                    supports_alt = base == alt.upper()
                    supports_ref = base == ref.upper()
                elif len(alt) > len(ref) and alt.upper().startswith(ref.upper()):
                    inserted = alt[len(ref):].upper()
                    observed = read.query_sequence[query_pos + 1: query_pos + 1 + len(inserted)].upper()
                    supports_alt = pileup_read.indel == len(inserted) and observed == inserted
                    supports_ref = pileup_read.indel == 0
                elif len(ref) > len(alt) and ref.upper().startswith(alt.upper()):
                    deleted = len(ref) - len(alt)
                    supports_alt = pileup_read.indel == -deleted
                    supports_ref = pileup_read.indel == 0
                if supports_alt:
                    alt_count += 1
                    alt_fragments.add(str(getattr(read, "query_name", id(read))))
                    if read.is_reverse:
                        reverse += 1
                    else:
                        forward += 1
                elif supports_ref:
                    ref_count += 1
                    ref_fragments.add(str(getattr(read, "query_name", id(read))))
    except (ValueError, OSError) as exc:
        raise Track1Error(f"Could not inspect {chrom}:{pos}: {exc}") from exc
    mean_mq = statistics.fmean(mapqs) if mapqs else 0.0
    mean_bq = statistics.fmean(baseqs) if baseqs else 0.0
    vaf = alt_count / depth if depth else 0.0
    supported_representation = (len(ref) == len(alt) == 1 or
        (len(ref) == 1 and len(alt) > 1 and alt.upper().startswith(ref.upper())) or
        (len(alt) == 1 and len(ref) > 1 and ref.upper().startswith(alt.upper())))
    if not supported_representation:
        # Complex replacements/MNVs require haplotype-aware local realignment.
        # An unimplemented representation is not evidence of an absent allele.
        support = "ambiguous"
    elif (
        depth >= int(cfg["min_depth"])
        and alt_count >= int(cfg["min_alt_reads"])
        and forward >= 1
        and reverse >= 1
    ):
        support = "supported"
    elif depth >= int(cfg["min_depth"]) and alt_count == 0:
        support = "unsupported"
    else:
        support = "ambiguous"
    return {
        "depth": depth,
        "ref_reads": ref_count,
        "alt_reads": alt_count,
        "vaf": vaf,
        "alt_forward": forward,
        "alt_reverse": reverse,
        "mean_mapping_quality": mean_mq,
        "mean_base_quality": mean_bq,
        "support": support,
        "alt_fragments": alt_fragments,
        "ref_fragments": ref_fragments,
    }


def _phase_from_observations(
    one: dict[str, Any],
    two: dict[str, Any],
    min_fragments: int,
) -> tuple[str, int, int, int]:
    cis = one["alt_fragments"] & two["alt_fragments"]
    trans = (
        (one["alt_fragments"] & two["ref_fragments"])
        | (one["ref_fragments"] & two["alt_fragments"])
    )
    informative = cis | trans
    if len(trans) >= min_fragments and not cis:
        status = "read_linkage_supports_trans"
    elif len(cis) >= min_fragments and not trans:
        status = "read_linkage_supports_cis"
    elif cis and trans:
        status = "conflicting_read_linkage"
    else:
        status = "unresolved_insufficient_linkage"
    return status, len(informative), len(cis), len(trans)


def _load_whatshap_calls(
    phased_vcf: Path,
    sample_id: str,
    pysam: Any,
) -> dict[tuple[str, int, str, str], tuple[int, str]]:
    calls: dict[tuple[str, int, str, str], tuple[int, str]] = {}
    with pysam.VariantFile(str(phased_vcf)) as variants:
        if sample_id not in variants.header.samples:
            raise Track1Error(
                f"Configured sample {sample_id!r} is absent from Whatshap VCF"
            )
        for record in variants:
            if not record.alts or len(record.alts) != 1:
                continue
            sample = record.samples[sample_id]
            genotype = sample.get("GT")
            phase_set = sample.get("PS")
            if (
                not sample.phased
                or genotype is None
                or tuple(genotype).count(1) != 1
                or phase_set is None
            ):
                continue
            calls[
                (record.contig, record.pos, record.ref.upper(), record.alts[0].upper())
            ] = (tuple(genotype).index(1), str(phase_set))
    return calls


def _phase_from_whatshap(
    calls: dict[tuple[str, int, str, str], tuple[int, str]],
    first: tuple[str, int, str, str],
    second: tuple[str, int, str, str],
) -> tuple[str, str] | None:
    one = calls.get(first)
    two = calls.get(second)
    if one is None or two is None or one[1] != two[1]:
        return None
    orientation = "cis" if one[0] == two[0] else "trans"
    return f"whatshap_supports_{orientation}", one[1]


def validate_finalist_reads(
    cram: Path,
    reference: Path,
    candidates_path: Path,
    finalists_path: Path,
    output: Path,
    phased_vcf: Path | None = None,
    sample_id: str | None = None,
    config_path: Path | str = DEFAULT_CONFIG,
) -> None:
    try:
        import pysam
    except ImportError as exc:
        raise Track1Error("pysam is required for raw-read validation") from exc
    cfg = load_jsonish(config_path)["validation"]
    whatshap_calls = (
        _load_whatshap_calls(phased_vcf, sample_id, pysam)
        if phased_vcf is not None and sample_id is not None
        else {}
    )
    with candidates_path.open(encoding="utf-8", newline="") as handle:
        candidates = {row["candidate_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    selected = reviewed_finalists(finalists_path, candidates_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with pysam.AlignmentFile(str(cram), "rc", reference_filename=str(reference)) as alignment, output.open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=READ_VALIDATION_FIELDS, delimiter="\t")
        writer.writeheader()
        for reviewed in selected:
            candidate = candidates[reviewed["candidate_id"]]
            one = _allele_observation(
                alignment, candidate["chrom_1"], int(candidate["pos_1"]), candidate["ref_1"], candidate["alt_1"], cfg
            )
            two = None
            if candidate.get("chrom_2"):
                two = _allele_observation(
                    alignment, candidate["chrom_2"], int(candidate["pos_2"]), candidate["ref_2"], candidate["alt_2"], cfg
                )
            supports = [one["support"]] + ([two["support"]] if two else [])
            pair_support = "supported" if all(value == "supported" for value in supports) else (
                "unsupported" if "unsupported" in supports else "ambiguous"
            )
            if two is None:
                phase_status, informative, cis, trans = (
                    "not_applicable_single_variant", 0, 0, 0
                )
                phase_method, phase_set = "not_applicable", ""
            elif candidate["chrom_1"] != candidate["chrom_2"]:
                phase_status, informative, cis, trans = (
                    "not_applicable_different_chromosomes", 0, 0, 0
                )
                phase_method, phase_set = "not_applicable", ""
            else:
                phase_status, informative, cis, trans = _phase_from_observations(
                    one, two, int(cfg.get("min_phase_fragments", 2))
                )
                phase_method, phase_set = "direct_fragment_linkage", ""
                first_key = (
                    candidate["chrom_1"],
                    int(candidate["pos_1"]),
                    candidate["ref_1"].upper(),
                    candidate["alt_1"].upper(),
                )
                second_key = (
                    candidate["chrom_2"],
                    int(candidate["pos_2"]),
                    candidate["ref_2"].upper(),
                    candidate["alt_2"].upper(),
                )
                whatshap = _phase_from_whatshap(
                    whatshap_calls, first_key, second_key
                )
                if whatshap:
                    whatshap_status, phase_set = whatshap
                    direct_orientation = (
                        "trans" if phase_status == "read_linkage_supports_trans"
                        else "cis" if phase_status == "read_linkage_supports_cis"
                        else None
                    )
                    whatshap_orientation = whatshap_status.rsplit("_", 1)[-1]
                    if direct_orientation and direct_orientation != whatshap_orientation:
                        phase_status = "conflicting_phase_methods"
                        phase_method = "whatshap_and_direct_fragment_linkage"
                    else:
                        phase_status = whatshap_status
                        phase_method = "whatshap"
            row: dict[str, Any] = {
                "candidate_id": reviewed["candidate_id"],
                "pair_support": pair_support,
                "phase_status": phase_status,
                "phase_method": phase_method,
                "whatshap_phase_set": phase_set,
                "phase_informative_fragments": informative,
                "phase_cis_fragments": cis,
                "phase_trans_fragments": trans,
            }
            for prefix, observation in (("v1", one), ("v2", two)):
                for source, suffix in (
                    ("depth", "depth"), ("ref_reads", "ref_reads"), ("alt_reads", "alt_reads"),
                    ("vaf", "vaf"), ("alt_forward", "alt_forward"), ("alt_reverse", "alt_reverse"),
                    ("mean_mapping_quality", "mean_mq"), ("mean_base_quality", "mean_bq"), ("support", "support"),
                ):
                    row[f"{prefix}_{suffix}"] = "" if observation is None else observation[source]
            writer.writerow(row)
