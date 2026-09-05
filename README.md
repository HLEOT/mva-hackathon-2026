# MVA Hackathon 2026 — Track 1

Reproducible, local-only prioritisation of candidate variants for the
**Rare Disease, Real Kid: MVA Hackathon 2026**. The workflow starts from the
provided GRCh38 VCF and reviewed HPO terms, ranks plausible
compound-heterozygous pairs, and uses the raw FASTQs only to validate selected
finalists.

This repository contains code and configuration templates only. Gated source
data, patient-derived intermediates, tokens, and local submission artifacts are
ignored by Git.

## Model execution plan

The existing Track 1 workflow is being extended to both hackathon tracks.
The full implementation and execution contract is in
[docs/00_execution_plan.md](docs/00_execution_plan.md), including the ordered
file structure, commenting standard, resource limits, resumable milestones,
and completion checks. Give the model the copy-and-paste prompt in
[prompts/one_shot.md](prompts/one_shot.md) to implement or resume that plan.

Audited code and documentation may be published in small, focused commits as
work is ready. Intermediate commits do not establish scientific completion;
private data and generated submission materials remain local. The quick start
below documents the existing Track 1 interface.

## Safety boundaries

- Never commit or redistribute challenge data.
- Never send phenotype text, VCF records, genomic coordinates, or derived
  patient-level prompts to hosted APIs or LLMs.
- `HF_TOKEN` is read from the process environment or the owner-readable,
  Git-ignored `config/hf_token.local.txt`; it is never logged or copied.
- Hugging Face Hub and Xet caches are forced under the ignored
  `data/gated/huggingface-cache/` tree and removed by the bounded purge.
- The launcher enforces `umask 077`; gated files, private intermediates,
  workflow logs, and Snakemake metadata remain owner-only on shared hosts.
- Placeholder phenotype or finalist reviews are rejected. Raw FASTQs are not
  downloaded until the finalist rationale/rank/type gate passes.
- This is research prioritisation, not a clinical diagnosis or medical advice.
- The workflow does not automatically publish code or upload a submission.

## Quick start

```bash
# Create the launcher environment and run the synthetic test suite.
./mva-track1 bootstrap

# Put only an approved Hugging Face read token on the first line of the
# owner-readable, Git-ignored local token file, then fetch and verify the VCF,
# TBI, and phenotype document.
# $EDITOR config/hf_token.local.txt
./mva-track1 download-core

# Extract HPO terms, then review the generated private configuration.
./mva-track1 phenotype
cp config/proband.draft.local.yaml config/proband.local.yaml
# Verify every suggested present/absent term against the private source text,
# then replace reviewer/date placeholders in config/proband.local.yaml.

# Build the pinned public GRCh38, VEP, and Exomiser resources. This is
# independent of patient phenotype review and is safely resumable. Keep ample
# free space for the large Exomiser archives plus their extracted databases.
./mva-track1 prepare-public --cores 32

# Run normalization, offline annotation, Exomiser, and deterministic ranking.
./mva-track1 run --cores 32

# Review finalists, fetch the eight FASTQs, align once, validate alleles, and
# attempt read-backed phase with Whatshap across each finalist interval.
./mva-track1 validate-finalists --cores 64

# Generate and audit the official CSV and methods report.
./mva-track1 package --cores 8
```

Use `./mva-track1 status` for a concise readiness report. All commands are
resumable through Snakemake. Status verifies recorded sizes and all small-file
hashes without rehashing the large CRAM or public archives; `package` performs
the full checksum gate before constructing a deliverable.

## Main outputs

- `results/private/candidates_ranked.tsv`: full local evidence table.
- `results/private/read_validation.tsv`: candidate-level raw-read evidence.
- `results/private/final_run_manifest.json`: post-validation input hashes and
  exact scheduler plus per-stage Conda package versions/builds.
- `submissions/<hf-user>_track1-ranked.csv`: schema-validated Track 1 CSV.
- `submissions/<hf-user>_track1_report.md` and `.pdf`: methods report.
- `submissions/<hf-user>_track1_bundle.zip`: audited deliverable bundle.

The official CSV is limited to ten rows and uses `PROBAND01`, GRCh38 `chr*`
coordinates, canonical compound-heterozygous pair ordering, and unique EPCR
ranking values.

## Submission checklist

Recheck the [official challenge rules](https://sagebio-rare-disease-real-kid-mva-hackathon-2026.hf.space/)
at submission time. In addition to the Track 1 CSV, the submission must include:

- A written report (the package command produces Markdown and PDF versions).
- A public GitHub repository and its canonical `https://github.com/<owner>/<repo>`
  URL, containing no gated data or patient-derived artifacts.
- A recorded pitch video no longer than three minutes.
- For every publication, preprint, conference abstract, or public communication,
  the exact acknowledgement required by the official rules and the dataset
  citation provided on the Hackathon Synapse page at that time.
- Continued compliance with the embargo, data-subject privacy, no-recontact,
  no-resharing, deletion, and deletion-confirmation obligations in the rules.

## Data lifecycle

`./mva-track1 purge-gated --dry-run` prints the exact local targets governed by
the deletion policy. `--confirm` requires an additional typed confirmation,
deletes only those resolved paths—including patient-adjacent logs and
Snakemake metadata—and writes a non-sensitive deletion receipt outside the
deleted tree. Run it no later than 30 days after the challenge closes, then
send the required confirmation to the organizers.

## Reproducibility

The workflow records the Hugging Face dataset revision, file metadata and
SHA-256 checksums, public reference URLs/checksums, hashes of the Conda
environment definitions and workflow configuration, exact solved Conda package
versions/builds from the actual scheduler and each rule stage, parameters, the
Python workflow sources, launcher, project metadata, and the Git commit in each
run manifest. A second manifest is generated only after
raw-read validation so BWA-MEM2, samtools, Whatshap, FastQC, and MultiQC
provenance cannot go stale. Exomiser 15.1.0 is pinned to its compatible 2602
database release and the coding/splice-focused exome preset; the VEP lane
retains genome-wide annotations. Public resources are cached locally but are
not committed.
