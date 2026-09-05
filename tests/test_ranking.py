from __future__ import annotations

import csv
from pathlib import Path

from mva_track1.ranking import rank_vcf


VCF = """##fileformat=VCFv4.2
##reference=GRCh38
##contig=<ID=chr1,length=248956422>
##contig=<ID=chr15,length=101991189>
##INFO=<ID=CSQ,Number=.,Type=String,Description="VEP. Format: Allele|Consequence|IMPACT|SYMBOL|Gene|Feature|MAX_AF|gnomADe_AF|gnomADg_AF|CLIN_SIG">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##FORMAT=<ID=GQ,Number=1,Type=Integer,Description="Genotype quality">
##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE01
chr15\t100\t.\tA\tG\t100\tPASS\tCSQ=G|stop_gained|HIGH|BUB1B|ENSG1|ENST1|0.0001||||Pathogenic\tGT:GQ:DP\t0/1:60:35
chr15\t200\t.\tC\tT\t100\tPASS\tCSQ=T|missense_variant|MODERATE|BUB1B|ENSG1|ENST1|0.0002||||\tGT:GQ:DP\t0/1:50:30
chr1\t300\t.\tG\tA\t100\tPASS\tCSQ=A|missense_variant|MODERATE|OTHER|ENSG2|ENST2|0.00001||||\tGT:GQ:DP\t0/1:60:30
chr1\t400\t.\tT\tC\t100\tPASS\tCSQ=C|missense_variant|MODERATE|OTHER|ENSG2|ENST2|0.00001||||\tGT:GQ:DP\t0/1:60:30
"""


def test_known_mva_compound_het_ranks_first(tmp_path: Path) -> None:
    vcf = tmp_path / "annotated.vcf"
    vcf.write_text(VCF, encoding="utf-8")
    exomiser = tmp_path / "exomiser.tsv"
    exomiser.write_text(
        "CONTIG\tSTART\tREF\tALT\tGENE_SYMBOL\tEXOMISER_SCORE\n"
        "chr15\t100\tA\tG\tBUB1B\t0.8\n"
        "chr15\t200\tC\tT\tBUB1B\t0.8\n"
        "chr1\t300\tG\tA\tOTHER\t0.95\n"
        "chr1\t400\tT\tC\tOTHER\t0.95\n",
        encoding="utf-8",
    )
    output = tmp_path / "candidates.tsv"
    candidates = rank_vcf(vcf, "SAMPLE01", output, exomiser)
    assert candidates[0].gene == "BUB1B"
    assert candidates[0].tier == "A"
    assert candidates[0].variant_2 is not None
    with output.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[0]["candidate_id"].startswith("BUB1B|")
    assert rows[0]["pos_1"] == "100"
    assert rows[0]["pos_2"] == "200"


def test_population_filter_removes_common_variant(tmp_path: Path) -> None:
    common = VCF.replace("0.0002", "0.2")
    vcf = tmp_path / "annotated.vcf"
    vcf.write_text(common, encoding="utf-8")
    output = tmp_path / "candidates.tsv"
    candidates = rank_vcf(vcf, "SAMPLE01", output)
    assert not any(
        item.gene == "BUB1B" and item.variant_2 is not None for item in candidates
    )
