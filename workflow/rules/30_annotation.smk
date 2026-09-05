# GRCh38 allele normalisation and offline annotation, independent of phenotype wording.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule check_reference:
    input:
        vcf=VCF,
        fai=REFERENCE_FAI,
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/vcf.py"]
    output:
        receipt="work/private/reference_check.json",
        aliases="work/private/reference_contig_aliases.tsv"
    log:
        "logs/check_reference.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks reference-check "
        "--vcf {input.vcf:q} --fai {input.fai:q} --output {output.receipt:q} "
        "--rename-map {output.aliases:q} > {log:q} 2>&1"


rule normalize_vcf:
    input:
        vcf=VCF,
        tbi=TBI,
        reference=REFERENCE,
        reference_check="work/private/reference_check.json",
        aliases="work/private/reference_contig_aliases.tsv"
    output:
        vcf="work/private/variants/PROBAND01.normalized.vcf.gz",
        tbi="work/private/variants/PROBAND01.normalized.vcf.gz.tbi"
    log:
        "logs/normalize_vcf.log"
    threads: 8
    conda:
        "../envs/hts.yaml"
    shell:
        "mkdir -p logs work/private/variants && exec >{log:q} 2>&1 && "
        "bcftools annotate --rename-chrs {input.aliases:q} --output-type u {input.vcf:q} | "
        "bcftools norm --threads {threads} --check-ref e --fasta-ref {input.reference:q} "
        "--multiallelics -any --old-rec-tag ORIGINAL_RECORD --output-type z "
        "--output {output.vcf:q} - && "
        "bcftools index --threads {threads} --tbi {output.vcf:q}"


rule annotate_vep:
    input:
        vcf="work/private/variants/PROBAND01.normalized.vcf.gz",
        tbi="work/private/variants/PROBAND01.normalized.vcf.gz.tbi",
        reference=REFERENCE,
        cache=VEP_CACHE_MARKER,
        cache_manifest=VEP_CACHE_MANIFEST
    output:
        vcf="work/private/variants/PROBAND01.vep.vcf.gz",
        tbi="work/private/variants/PROBAND01.vep.vcf.gz.tbi"
    log:
        "logs/annotate_vep.log"
    params:
        cache=lambda wildcards, input: str(Path(input.cache).parent),
        version=config["annotation"]["vep_version"]
    threads: 16
    conda:
        "../envs/annotation.yaml"
    shell:
        "mkdir -p logs && exec >{log:q} 2>&1 && "
        "vep --input_file {input.vcf:q} --output_file {output.vcf:q} --vcf "
        "--compress_output bgzip --force_overwrite --offline --cache --merged "
        "--cache_version {params.version} --assembly GRCh38 --dir_cache {params.cache:q} "
        "--fasta {input.reference:q} --everything --fork {threads} --check_ref && "
        "tabix -f -p vcf {output.vcf:q}"
