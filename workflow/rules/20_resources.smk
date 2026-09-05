# Pinned public resources. Preserve verified installations on resume.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule download_reference:
    output:
        fasta=REFERENCE,
        fai=REFERENCE_FAI,
        dictionary=REFERENCE_DICT,
        manifest="resources/public/manifest.json"
    log:
        "logs/download_reference.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks reference "
        "--output {output.fasta:q} > {log:q} 2>&1"


rule install_vep_cache:
    input:
        reference=REFERENCE
    output:
        marker=VEP_CACHE_MARKER,
        manifest=VEP_CACHE_MANIFEST
    log:
        "logs/install_vep_cache.log"
    params:
        cache=lambda wildcards, output: str(Path(output[0]).parent),
        version=config["annotation"]["vep_version"]
    conda:
        "../envs/annotation.yaml"
    shell:
        "mkdir -p logs {params.cache:q} && "
        "vep_install -a c -s homo_sapiens_merged -y GRCh38 -c {params.cache:q} "
        "--CACHE_VERSION {params.version} --NO_HTSLIB > {log:q} 2>&1 && "
        "vep --offline --cache --merged --species homo_sapiens "
        "--cache_version {params.version} --assembly GRCh38 "
        "--dir_cache {params.cache:q} --fasta {input.reference:q} "
        "--format vcf --input_file /dev/null "
        "--output_file /dev/null --force_overwrite --no_headers --no_stats --quiet "
        ">> {log:q} 2>&1 && "
        "PYTHONPATH=src python -m mva_track1.workflow_tasks verify-vep-cache "
        "--output {output.marker:q} --manifest {output.manifest:q} >> {log:q} 2>&1"


rule install_exomiser:
    output:
        marker=EXOMISER_MARKER,
        manifest=EXOMISER_MANIFEST
    log:
        "logs/install_exomiser.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks install-exomiser "
        "--output {output.marker:q} > {log:q} 2>&1"


rule index_bwa_reference:
    input:
        REFERENCE
    output:
        indexes=BWA_INDEX,
        marker=touch(BWA_INDEX_MARKER)
    log:
        "logs/index_bwa_reference.log"
    threads: 16
    conda:
        # This byte-preserved definition is the index's original toolchain.
        # Adding read-QC/parser dependencies must not erase and rebuild an
        # unchanged index. Its legacy environment name is intentional.
        "../envs/bwa_index.yaml"
    shell:
        "mkdir -p logs && bwa-mem2 index {input:q} > {log:q} 2>&1 && touch {output.marker:q}"


rule record_bwa_provenance:
    input:
        reference=REFERENCE,
        fai=REFERENCE_FAI,
        indexes=BWA_INDEX + [BWA_INDEX_MARKER],
        reference_manifest="resources/public/manifest.json",
        index_environment="workflow/envs/bwa_index.yaml",
        reads_environment="workflow/envs/reads.yaml",
        code=["src/mva_runner/bwa_provenance.py", "src/mva_track1/common.py", "src/mva_track1/workflow_tasks.py"]
    output:
        BWA_INDEX_PROVENANCE
    log:
        "logs/record_bwa_provenance.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_runner.bwa_provenance "
        "--reference {input.reference:q} --output {output:q} > {log:q} 2>&1"
