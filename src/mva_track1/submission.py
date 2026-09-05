from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .common import Track1Error


SUBMISSION_FIELDS = [
    "proband_id", "chrom_1", "pos_1", "ref_1", "alt_1",
    "chrom_2", "pos_2", "ref_2", "alt_2", "epcr", "finding_type", "notes",
]


def normalize_chrom(chrom: str) -> str:
    value = chrom.strip()
    if value.lower().startswith("chr"):
        value = value[3:]
    if value == "MT":
        value = "M"
    if value not in {str(number) for number in range(1, 23)} | {"X", "Y", "M"}:
        raise Track1Error(f"Unsupported GRCh38 chromosome name: {chrom}")
    return f"chr{value}"


def _variant_key(row: dict[str, str], suffix: str) -> tuple[int, int, str, str, str]:
    chrom = normalize_chrom(row[f"chrom_{suffix}"])
    raw = chrom[3:]
    order = int(raw) if raw.isdigit() else {"X": 23, "Y": 24, "M": 25}[raw]
    pos = int(row[f"pos_{suffix}"])
    return order, pos, row[f"ref_{suffix}"].upper(), row[f"alt_{suffix}"].upper(), chrom


def _candidate_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["candidate_id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def prepare_finalists(candidates_path: Path, finalists_path: Path, limit: int = 10) -> None:
    if finalists_path.exists():
        raise Track1Error(f"Refusing to overwrite existing finalist review: {finalists_path}")
    candidates = list(_candidate_rows(candidates_path).values())[:limit]
    finalists_path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["candidate_id", "selected", "final_rank", "finding_type", "review_reason"]
    with finalists_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        for rank, row in enumerate(candidates, 1):
            writer.writerow(
                {
                    "candidate_id": row["candidate_id"],
                    "selected": "YES",
                    "final_rank": rank,
                    "finding_type": "primary",
                    "review_reason": "REVIEW REQUIRED",
                }
            )


def reviewed_finalists(
    path: Path,
    candidates_path: Path | None = None,
) -> list[dict[str, str]]:
    if not path.is_file():
        raise Track1Error("Missing config/finalists.local.tsv; prepare and review finalists first")
    with path.open(encoding="utf-8", newline="") as handle:
        selected = [
            row
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("selected", "").strip().upper() in {"YES", "Y", "TRUE", "1"}
        ]
    if not selected:
        raise Track1Error("Finalist review selects no candidates")
    for row in selected:
        reason = re.sub(r"\s+", " ", str(row.get("review_reason", ""))).strip()
        if not reason or reason.casefold() == "review required":
            raise Track1Error(f"Finalist {row.get('candidate_id')} lacks a reviewed rationale")
        row["review_reason"] = reason
        try:
            rank = int(str(row["final_rank"]).strip())
        except (KeyError, TypeError, ValueError) as exc:
            raise Track1Error(f"Invalid final_rank for {row.get('candidate_id')}") from exc
        if rank <= 0:
            raise Track1Error(f"Invalid final_rank for {row.get('candidate_id')}")
        row["final_rank"] = str(rank)
        finding_type = str(row.get("finding_type", "")).strip().lower()
        if finding_type not in {"primary", "secondary"}:
            raise Track1Error("finding_type must be primary or secondary")
        row["finding_type"] = finding_type
        row["candidate_id"] = str(row.get("candidate_id", "")).strip()
    selected.sort(key=lambda item: int(item["final_rank"]))
    if len(selected) > 10:
        raise Track1Error("At most 10 finalists may be selected")
    if len({int(row["final_rank"]) for row in selected}) != len(selected):
        raise Track1Error("final_rank values must be unique")
    if [int(row["final_rank"]) for row in selected] != list(
        range(1, len(selected) + 1)
    ):
        raise Track1Error("final_rank values must be contiguous starting at 1")
    candidate_ids = [row.get("candidate_id", "") for row in selected]
    if not all(candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
        raise Track1Error("Selected candidate_id values must be present and unique")
    if candidates_path is not None:
        candidates = _candidate_rows(candidates_path)
        missing = [candidate_id for candidate_id in candidate_ids if candidate_id not in candidates]
        if missing:
            raise Track1Error(f"Reviewed finalist no longer exists: {missing[0]}")
    return selected


def _validation(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["candidate_id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def build_submission(
    candidates_path: Path,
    finalists_path: Path,
    output_path: Path,
    validation_path: Path | None = None,
) -> list[dict[str, str]]:
    candidates = _candidate_rows(candidates_path)
    finalists = reviewed_finalists(finalists_path, candidates_path)
    validation = _validation(validation_path)
    rows: list[dict[str, str]] = []
    count = len(finalists)
    for index, reviewed in enumerate(finalists):
        candidate_id = reviewed["candidate_id"]
        if candidate_id not in candidates:
            raise Track1Error(f"Reviewed finalist no longer exists: {candidate_id}")
        candidate = candidates[candidate_id]
        if candidate.get("chrom_2"):
            first = _variant_key(candidate, "1")
            second = _variant_key(candidate, "2")
            suffixes = ("1", "2") if first <= second else ("2", "1")
        else:
            suffixes = ("1", None)
        epcr = 0.95 if count == 1 else 0.95 - index * (0.90 / (count - 1))
        support = validation.get(candidate_id, {}).get("pair_support", "not_raw_validated")
        phase = validation.get(candidate_id, {}).get("phase_status", "not_raw_validated")
        notes = (
            f"{candidate['gene']}; raw_read_support={support}; phase={phase}; "
            f"{reviewed['review_reason']}"
        )
        one, two = suffixes
        rows.append(
            {
                "proband_id": "PROBAND01",
                "chrom_1": normalize_chrom(candidate[f"chrom_{one}"]),
                "pos_1": candidate[f"pos_{one}"],
                "ref_1": candidate[f"ref_{one}"].upper(),
                "alt_1": candidate[f"alt_{one}"].upper(),
                "chrom_2": normalize_chrom(candidate[f"chrom_{two}"]) if two else "",
                "pos_2": candidate[f"pos_{two}"] if two else "",
                "ref_2": candidate[f"ref_{two}"].upper() if two else "",
                "alt_2": candidate[f"alt_{two}"].upper() if two else "",
                "epcr": f"{epcr:.6f}",
                "finding_type": reviewed["finding_type"],
                "notes": notes,
            }
        )
    validate_submission_rows(rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUBMISSION_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def validate_submission_rows(rows: list[dict[str, Any]]) -> None:
    if not 1 <= len(rows) <= 10:
        raise Track1Error("Submission must contain 1 to 10 rows")
    epcrs: list[float] = []
    candidate_sets: set[frozenset[tuple[str, int, str, str]]] = set()
    for row in rows:
        missing = [field for field in SUBMISSION_FIELDS[:5] if str(row.get(field, "")).strip() == ""]
        if missing:
            raise Track1Error(f"Submission row is missing: {', '.join(missing)}")
        if row["proband_id"] != "PROBAND01":
            raise Track1Error("Only PROBAND01 is accepted")
        variants = {
            (
                normalize_chrom(str(row["chrom_1"])), int(row["pos_1"]),
                str(row["ref_1"]).upper(), str(row["alt_1"]).upper(),
            )
        }
        second_fields = [str(row.get(field, "")).strip() for field in ("chrom_2", "pos_2", "ref_2", "alt_2")]
        if any(second_fields) and not all(second_fields):
            raise Track1Error("Second-variant fields must be either all filled or all blank")
        if all(second_fields):
            variants.add(
                (
                    normalize_chrom(second_fields[0]), int(second_fields[1]),
                    second_fields[2].upper(), second_fields[3].upper(),
                )
            )
        frozen = frozenset(variants)
        if frozen in candidate_sets:
            raise Track1Error("Duplicate candidate row")
        candidate_sets.add(frozen)
        epcr = float(row["epcr"])
        if not 0 < epcr <= 1:
            raise Track1Error("EPCR must be in (0,1]")
        epcrs.append(epcr)
        if row.get("finding_type") not in {"primary", "secondary"}:
            raise Track1Error("finding_type must be primary or secondary")
        for allele in (row["ref_1"], row["alt_1"], row.get("ref_2", ""), row.get("alt_2", "")):
            if allele and not re.fullmatch(r"[ACGTN]+|<[^>]+>|\*", str(allele).upper()):
                raise Track1Error(f"Invalid allele: {allele}")
    if epcrs != sorted(epcrs, reverse=True) or len(epcrs) != len(set(epcrs)):
        raise Track1Error("EPCR values must be unique and strictly descending")


def validate_submission_file(path: Path) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != SUBMISSION_FIELDS:
            raise Track1Error(f"Unexpected submission columns: {reader.fieldnames}")
        validate_submission_rows(list(reader))
