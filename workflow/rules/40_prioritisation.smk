# Phenotype scoring and candidate ranking; retain the historical comparator.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule make_phenopacket:
    input:
        review="work/private/phenotype_review.ok",
        config=PROBAND_CONFIG,
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/exomiser.py","src/mva_track1/phenotype.py"]
    output:
        "work/private/phenotype/PROBAND01.phenopacket.json"
    log:
        "logs/make_phenopacket.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks phenopacket "
        "--config {input.config:q} --output {output:q} > {log:q} 2>&1"


rule run_exomiser:
    input:
        vcf="work/private/variants/PROBAND01.normalized.vcf.gz",
        phenopacket="work/private/phenotype/PROBAND01.phenopacket.json",
        installed=EXOMISER_MARKER,
        install_manifest=EXOMISER_MANIFEST,
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/exomiser.py"],
        settings="config/config.yaml"
    output:
        "work/private/exomiser/PROBAND01.variants.tsv"
    log:
        "logs/run_exomiser.log"
    conda:
        "../envs/annotation.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks exomiser "
        "--vcf {input.vcf:q} --phenopacket {input.phenopacket:q} "
        "--output-dir work/private/exomiser --output {output:q} > {log:q} 2>&1"


rule rank_candidates:
    input:
        vcf="work/private/variants/PROBAND01.vep.vcf.gz",
        exomiser="work/private/exomiser/PROBAND01.variants.tsv",
        review="work/private/phenotype_review.ok",
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/ranking.py","src/mva_track1/vcf.py"],
        settings="config/config.yaml"
    output:
        ranked="results/private/candidates_ranked.tsv",
        baseline="results/private/candidates_baseline.tsv"
    log:
        "logs/rank_candidates.log"
    params:
        sample=lambda wildcards: PROBAND["vcf_sample_id"]
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks rank "
        "--vcf {input.vcf:q} --sample {params.sample:q} --exomiser {input.exomiser:q} "
        "--output {output.ranked:q} > {log:q} 2>&1"
