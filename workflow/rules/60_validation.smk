# Finalist-level read support and phase; unresolved evidence remains unresolved.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule validate_finalists_review:
    input:
        candidates="results/private/candidates_ranked.tsv",
        finalists="config/finalists.local.tsv",
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/submission.py"],
        settings="config/config.yaml"
    output:
        "work/private/finalists_review.ok"
    log:
        "logs/validate_finalists_review.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks "
        "validate-finalists-review --candidates {input.candidates:q} "
        "--finalists {input.finalists:q} --output {output:q} > {log:q} 2>&1"


rule make_finalist_regions:
    input:
        candidates="results/private/candidates_ranked.tsv",
        finalists="config/finalists.local.tsv",
        review="work/private/finalists_review.ok",
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/validation.py","src/mva_track1/submission.py","src/mva_track1/vcf.py"],
        settings="config/config.yaml"
    output:
        "work/private/validation/finalist_intervals.tsv"
    log:
        "logs/make_finalist_regions.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks finalist-regions "
        "--candidates {input.candidates:q} --finalists {input.finalists:q} "
        "--output {output:q} > {log:q} 2>&1"


rule subset_finalist_intervals:
    input:
        vcf="work/private/variants/PROBAND01.normalized.vcf.gz",
        tbi="work/private/variants/PROBAND01.normalized.vcf.gz.tbi",
        regions="work/private/validation/finalist_intervals.tsv"
    output:
        vcf="work/private/validation/finalist_intervals.vcf.gz",
        tbi="work/private/validation/finalist_intervals.vcf.gz.tbi"
    log:
        "logs/subset_finalist_intervals.log"
    conda:
        "../envs/reads.yaml"
    shell:
        "mkdir -p logs && exec >{log:q} 2>&1 && "
        "bcftools view --regions-file {input.regions:q} --output-type z "
        "--output {output.vcf:q} {input.vcf:q} && "
        "bcftools index --tbi {output.vcf:q}"


rule phase_finalists:
    input:
        vcf="work/private/validation/finalist_intervals.vcf.gz",
        tbi="work/private/validation/finalist_intervals.vcf.gz.tbi",
        cram=CRAM,
        crai=CRAI,
        reference=REFERENCE
    output:
        vcf="work/private/validation/finalist_intervals.phased.vcf.gz",
        tbi="work/private/validation/finalist_intervals.phased.vcf.gz.tbi"
    log:
        "logs/phase_finalists.log"
    params:
        sample=lambda wildcards: PROBAND["vcf_sample_id"]
    conda:
        "../envs/reads.yaml"
    shell:
        "mkdir -p logs && exec >{log:q} 2>&1 && "
        "whatshap phase --sample {params.sample:q} --reference {input.reference:q} "
        "--output {output.vcf:q} {input.vcf:q} {input.cram:q} && "
        "bcftools index --tbi {output.vcf:q}"


rule validate_reads:
    input:
        cram=CRAM,
        crai=CRAI,
        reference=REFERENCE,
        candidates="results/private/candidates_ranked.tsv",
        finalists="config/finalists.local.tsv",
        phased="work/private/validation/finalist_intervals.phased.vcf.gz",
        phased_tbi="work/private/validation/finalist_intervals.phased.vcf.gz.tbi",
        qc="work/private/qc/multiqc_report.html",
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/validation.py","src/mva_track1/submission.py","src/mva_track1/vcf.py"],
        settings="config/config.yaml"
    output:
        "results/private/read_validation.tsv"
    log:
        "logs/validate_reads.log"
    params:
        sample=lambda wildcards: PROBAND["vcf_sample_id"]
    conda:
        "../envs/reads.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks validate-reads "
        "--cram {input.cram:q} --reference {input.reference:q} "
        "--candidates {input.candidates:q} --finalists {input.finalists:q} "
        "--phased-vcf {input.phased:q} --sample {params.sample:q} "
        "--output {output:q} > {log:q} 2>&1"
