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
        "../envs/reads.yaml"
    shell:
        "mkdir -p logs && bwa-mem2 index {input:q} > {log:q} 2>&1 && touch {output.marker:q}"
