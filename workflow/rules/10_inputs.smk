# Private input and phenotype review gates. Detailed evidence stays in local logs.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule verify_core:
    input:
        manifest="data/gated/manifest.json",
        docx=DOCX,
        vcf=VCF,
        tbi=TBI,
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/download.py","src/mva_track1/vcf.py"],
        settings="config/config.yaml"
    output:
        "work/private/core_verified.json"
    log:
        "logs/verify_core.log"
    conda:
        "../envs/hts.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks verify-core "
        "> {log:q} 2>&1"


rule extract_phenotype:
    input:
        verified="work/private/core_verified.json",
        docx=DOCX,
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/phenotype.py"]
    output:
        extracted="work/private/phenotype_extracted.tsv"
    log:
        "logs/extract_phenotype.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks extract-phenotype "
        "--docx {input.docx:q} --output {output.extracted:q} "
        "--private-text work/private/phenotype_text_for_review.txt > {log:q} 2>&1"


rule validate_proband_review:
    input:
        extracted="work/private/phenotype_extracted.tsv",
        config=PROBAND_CONFIG,
        code=["src/mva_track1/common.py","src/mva_track1/workflow_tasks.py","src/mva_track1/phenotype.py"]
    output:
        "work/private/phenotype_review.ok"
    log:
        "logs/validate_proband_review.log"
    conda:
        "../envs/launcher.yaml"
    shell:
        "mkdir -p logs && PYTHONPATH=src python -m mva_track1.workflow_tasks validate-proband "
        "--config {input.config:q} --output {output:q} > {log:q} 2>&1"
