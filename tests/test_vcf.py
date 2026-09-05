from __future__ import annotations

from pathlib import Path

from mva_track1.vcf import iter_annotated_variants


CSQ_FIELDS = [
    "Allele",
    "ALLELE_NUM",
    "Consequence",
    "IMPACT",
    "SYMBOL",
    "Gene",
    "Feature",
    "MAX_AF",
    "gnomADe_AF",
    "gnomADg_AF",
    "CLIN_SIG",
]


def _csq(
    allele: str,
    allele_number: str,
    consequence: str,
    impact: str,
    gene: str,
    *,
    max_af: str = "",
    gnomadg_af: str = "",
) -> str:
    return "|".join(
        [
            allele,
            allele_number,
            consequence,
            impact,
            gene,
            f"ENSG_{gene}",
            f"ENST_{gene}",
            max_af,
            "",
            gnomadg_af,
            "",
        ]
    )


def test_vcf_csq_matches_normalized_snv_insertion_and_deletion(
    tmp_path: Path,
) -> None:
    wrong_allele_number = _csq(
        "G", "2", "stop_gained", "HIGH", "WRONG", max_af="0.9"
    )
    snv = _csq("G", "1", "synonymous_variant", "LOW", "SNV_GENE")
    insertion = _csq("T", "", "frameshift_variant", "HIGH", "INS_GENE")
    deletion = _csq(
        "-", "", "frameshift_variant", "HIGH", "DEL_GENE", gnomadg_af="0.003"
    )
    failed = _csq("C", "1", "stop_gained", "HIGH", "FILTERED_GENE")
    vcf = tmp_path / "synthetic.vcf"
    vcf.write_text(
        "##fileformat=VCFv4.2\n"
        f'##INFO=<ID=CSQ,Number=.,Type=String,Description="VEP. Format: {"|".join(CSQ_FIELDS)}">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE01\n"
        f"chr1\t100\t.\tA\tG\t.\tPASS\tAF=0.42;CSQ={wrong_allele_number},{snv}\tGT:GQ:DP\t0/1:60:30\n"
        f"chr1\t200\t.\tA\tAT\t.\tPASS\tMAX_AF=0.02;CSQ={insertion}\tGT:GQ:DP\t0/1:50:25\n"
        f"chr1\t300\t.\tAT\tA\t.\tPASS\tCSQ={deletion}\tGT:GQ:DP\t0/1:45:20\n"
        f"chr1\t400\t.\tA\tC\t.\tLowQual\tCSQ={failed}\tGT:GQ:DP\t0/1:60:30\n",
        encoding="utf-8",
    )

    records = list(iter_annotated_variants(vcf, "SAMPLE01"))
    assert [record.gene for record in records] == [
        "SNV_GENE",
        "INS_GENE",
        "DEL_GENE",
    ]
    by_position = {record.pos: record for record in records}
    assert by_position[100].max_af is None
    assert by_position[200].alt == "AT"
    assert by_position[200].max_af == 0.02
    assert by_position[300].ref == "AT"
    assert by_position[300].alt == "A"
    assert by_position[300].max_af == 0.003


def test_hgvs_and_transcript_stay_attached_to_the_selected_allele(tmp_path):
    fields = CSQ_FIELDS + ["HGVSc", "HGVSp"]
    wrong = _csq("T", "2", "stop_gained", "HIGH", "WRONG") + "|WRONG:c.1A%3ET|WRONG:p.Arg1Ter"
    correct = _csq("G", "1", "missense_variant", "MODERATE", "SYNTHETIC") + "|ENST_SYNTHETIC.1:c.35A%3EG|ENSP_SYNTHETIC.1:p.Arg12His"
    path = tmp_path / "synthetic.vcf"
    path.write_text('##fileformat=VCFv4.2\n'
        f'##INFO=<ID=CSQ,Number=.,Type=String,Description="VEP. Format: {"|".join(fields)}">\n'
        '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tSAMPLE01\n'
        f'chr1\t100\t.\tA\tG\t.\tPASS\tCSQ={wrong},{correct}\tGT:GQ:DP\t0/1:60:30\n')
    record, = iter_annotated_variants(path, "SAMPLE01")
    assert record.gene == "SYNTHETIC"
    assert record.transcript == "ENST_SYNTHETIC"
    assert record.hgvsc == "ENST_SYNTHETIC.1:c.35A>G"
    assert record.hgvsp == "ENSP_SYNTHETIC.1:p.Arg12His"
