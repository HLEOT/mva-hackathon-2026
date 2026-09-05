# Raw-read QC and one reusable duplicate-marked CRAM within the resource budget.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule fastq_qc:
    input:
        fastqs=R1 + R2
    output:
        "work/private/qc/multiqc_report.html"
    log:
        "logs/fastq_qc.log"
    threads: 16
    conda:
        "../envs/reads.yaml"
    shell:
        "mkdir -p logs work/private/qc/fastqc work/private/tmp/fastqc && "
        "chmod 700 work/private/tmp work/private/tmp/fastqc && "
        "export TMPDIR=$PWD/work/private/tmp/fastqc && exec >{log:q} 2>&1 && "
        "fastqc --threads {threads} --dir work/private/tmp/fastqc "
        "--outdir work/private/qc/fastqc {input.fastqs:q} && "
        "multiqc --force --no-megaqc-upload --no-version-check --no-ai "
        "--outdir work/private/qc work/private/qc/fastqc"


rule align_mark_duplicates:
    input:
        r1=R1,
        r2=R2,
        reference=REFERENCE,
        index=BWA_INDEX + [BWA_INDEX_MARKER, BWA_INDEX_PROVENANCE]
    output:
        cram=CRAM,
        crai=CRAI
    log:
        "logs/align_mark_duplicates.log"
    params:
        # Snakemake tracks the sample value, not phenotype review timestamps.
        read_group=lambda wildcards: (
            f"@RG\\tID:PROBAND01\\tSM:{PROBAND['vcf_sample_id']}\\tPL:ILLUMINA"
        ),
        bwa=lambda wildcards, threads: alignment_threads(threads)["bwa"],
        io=lambda wildcards, threads: alignment_threads(threads)["io"]
    threads: 96
    resources:
        mem_mb=180000
    conda:
        "../envs/reads.yaml"
    shell:
        r"""
        mkdir -p logs work/private/alignment work/private/tmp/sort-name work/private/tmp/sort-coordinate
        chmod 700 work/private/tmp work/private/tmp/sort-name work/private/tmp/sort-coordinate
        exec >{log:q} 2>&1
        # Each samtools -@ is an additional thread count. Streaming prevents a
        # complete BAM from coexisting on disk with the final CRAM.
        bwa-mem2 mem -t {params.bwa} -R {params.read_group:q} \
          {input.reference:q} <(gzip -cd {input.r1:q}) <(gzip -cd {input.r2:q}) |
        samtools sort -n -m 8G -T work/private/tmp/sort-name/prefix -@ {params.io} -O bam - |
        samtools fixmate -m -u -@ {params.io} - - |
        samtools sort -m 8G -T work/private/tmp/sort-coordinate/prefix -@ {params.io} -O bam - |
        samtools markdup -u -@ {params.io} - - |
        samtools view -@ {params.io} -C -T {input.reference:q} -o {output.cram:q} -
        samtools quickcheck -v {output.cram:q}
        samtools index -@ {params.io} {output.cram:q}
        """
