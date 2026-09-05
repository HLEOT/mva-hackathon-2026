from __future__ import annotations

from pathlib import Path


def _workflow_text() -> str:
    """Include the ordered files when checking the real scientific commands."""
    return Path("workflow/Snakefile").read_text() + "\n" + "\n".join(
        path.read_text() for path in sorted(Path("workflow/rules").glob("*.smk")))


def test_solved_tool_cli_contracts_are_pinned() -> None:
    snakefile = _workflow_text()
    reads_environment = Path("workflow/envs/reads.yaml").read_text(encoding="utf-8")
    vep_install_rule = snakefile.split("rule install_vep_cache:", 1)[1].split(
        "rule annotate_vep:", 1
    )[0]

    assert "whatshap phase --indels" not in snakefile
    assert "whatshap phase --sample" in snakefile
    for flag in ("--no-megaqc-upload", "--no-version-check", "--no-ai"):
        assert flag in snakefile
    assert "--dir work/private/tmp/fastqc" in snakefile
    assert "-T work/private/tmp/sort-name/prefix" in snakefile
    assert "-T work/private/tmp/sort-coordinate/prefix" in snakefile
    assert "chmod 700 work/private/tmp" in snakefile
    assert "gzip=1.14" in reads_environment
    assert "reference=REFERENCE" in vep_install_rule
    assert "--fasta {input.reference:q}" in vep_install_rule


def test_ordered_rules_are_all_included_and_conda_paths_resolve():
    import re
    snakefile = Path("workflow/Snakefile").read_text()
    includes = re.findall(r'^include: "([^"]+)"', snakefile, re.M)
    assert includes == sorted(includes)
    assert len(includes) == 8
    assert {Path("workflow") / name for name in includes} == set(Path("workflow/rules").glob("*.smk"))
    names = re.findall(r'^rule (\w+):', _workflow_text(), re.M)
    assert len(names) == len(set(names)) == 27
    for name in includes:
        path = Path("workflow") / name
        for environment in re.findall(r'conda:\s*"([^"]+)"', path.read_text()):
            assert (path.parent / environment).is_file()


def test_rank_inputs_track_scientific_code_and_retain_baseline():
    rule = _workflow_text().split("rule rank_candidates:", 1)[1].split("\nrule ", 1)[0]
    inputs = rule.split("    input:", 1)[1].split("    output:", 1)[0]
    for path in ["src/mva_track1/ranking.py", "src/mva_track1/vcf.py", "config/config.yaml"]:
        assert path in inputs
    assert 'baseline="results/private/candidates_baseline.tsv"' in rule
    assert '--output {output.ranked:q}' in rule


def test_alignment_is_independent_of_phenotype_reviews_and_finalist_changes():
    rule = _workflow_text().split("rule align_mark_duplicates:", 1)[1].split("\nrule ", 1)[0]
    inputs = rule.split("    input:", 1)[1].split("    output:", 1)[0]
    assert "PROBAND_CONFIG" not in inputs
    assert "finalists" not in inputs
    assert "PROBAND['vcf_sample_id']" in rule
    assert "read_group=" in rule


def test_index_toolchain_is_isolated_and_provenance_precedes_alignment():
    text = _workflow_text()
    rule = text.split("rule index_bwa_reference:", 1)[1].split("\nrule ", 1)[0]
    assert '"../envs/bwa_index.yaml"' in rule
    assert '"../envs/reads.yaml"' not in rule
    alignment = text.split("rule align_mark_duplicates:", 1)[1].split("\nrule ", 1)[0]
    assert "BWA_INDEX_PROVENANCE" in alignment.split("    output:", 1)[0]
    final = text.split("rule final_run_manifest:", 1)[1]
    assert "{input.bwa_provenance:q}" in final and "{input.bwa_index_environment:q}" in final
