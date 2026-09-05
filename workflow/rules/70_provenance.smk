# Provenance changes regenerate manifests without forcing alignment or annotation.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule run_manifest:
    input:
        candidates="results/private/candidates_ranked.tsv",
        core_manifest="data/gated/manifest.json",
        reference_manifest="resources/public/manifest.json",
        phenotype=PROBAND_CONFIG,
        config="config/config.yaml",
        snakefile="workflow/Snakefile",
        launcher_env="workflow/envs/launcher.yaml",
        hts_env="workflow/envs/hts.yaml",
        annotation_env="workflow/envs/annotation.yaml",
        reads_env="workflow/envs/reads.yaml",
        workflow_rules=RULE_SOURCES,
        python_sources=PYTHON_SOURCES
    output:
        "results/private/run_manifest.json"
    log:
        "logs/run_manifest.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks manifest --output {output:q} "
        "{input.core_manifest:q} {input.reference_manifest:q} {input.phenotype:q} "
        "{input.config:q} {input.snakefile:q} {input.launcher_env:q} {input.hts_env:q} "
        "{input.annotation_env:q} {input.reads_env:q} {input.workflow_rules:q} {input.python_sources:q} > {log:q} 2>&1"


rule final_run_manifest:
    input:
        candidates="results/private/candidates_ranked.tsv",
        validation="results/private/read_validation.tsv",
        qc="work/private/qc/multiqc_report.html",
        cram=CRAM,
        crai=CRAI,
        core_manifest="data/gated/manifest.json",
        reference_manifest="resources/public/manifest.json",
        phenotype=PROBAND_CONFIG,
        finalists="config/finalists.local.tsv",
        config="config/config.yaml",
        snakefile="workflow/Snakefile",
        launcher_env="workflow/envs/launcher.yaml",
        hts_env="workflow/envs/hts.yaml",
        annotation_env="workflow/envs/annotation.yaml",
        reads_env="workflow/envs/reads.yaml",
        bwa_index=BWA_INDEX_MARKER,
        vep_cache=VEP_CACHE_MARKER,
        vep_manifest=VEP_CACHE_MANIFEST,
        exomiser=EXOMISER_MARKER,
        exomiser_manifest=EXOMISER_MANIFEST,
        python_sources=PYTHON_SOURCES,
        launcher="mva-track1",
        project_metadata="pyproject.toml",
        workflow_rules=RULE_SOURCES
    output:
        "results/private/final_run_manifest.json"
    log:
        "logs/final_run_manifest.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks manifest "
        "--output {output:q} {input.candidates:q} {input.validation:q} {input.qc:q} "
        "{input.cram:q} {input.crai:q} {input.core_manifest:q} {input.reference_manifest:q} "
        "{input.phenotype:q} {input.finalists:q} {input.config:q} {input.snakefile:q} "
        "{input.launcher_env:q} {input.hts_env:q} {input.annotation_env:q} "
        "{input.reads_env:q} {input.bwa_index:q} {input.vep_cache:q} "
        "{input.vep_manifest:q} {input.exomiser:q} {input.exomiser_manifest:q} "
        "{input.python_sources:q} {input.launcher:q} {input.project_metadata:q} "
        "{input.workflow_rules:q} > {log:q} 2>&1"
