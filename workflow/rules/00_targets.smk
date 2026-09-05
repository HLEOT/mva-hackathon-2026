# Public entry points; dependencies, not numbering, determine execution.
# Python code inputs are explicit so edits cannot silently reuse stale results.

rule phenotype:
    input:
        "work/private/core_verified.json",
        "work/private/phenotype_extracted.tsv"


rule prioritise:
    input:
        "results/private/candidates_ranked.tsv",
        "results/private/run_manifest.json"


rule public_resources:
    input:
        REFERENCE,
        REFERENCE_FAI,
        REFERENCE_DICT,
        "resources/public/manifest.json",
        VEP_CACHE_MARKER,
        VEP_CACHE_MANIFEST,
        EXOMISER_MARKER,
        EXOMISER_MANIFEST


rule validate_finalists:
    input:
        "results/private/read_validation.tsv",
        "work/private/qc/multiqc_report.html",
        CRAI,
        "results/private/final_run_manifest.json"
