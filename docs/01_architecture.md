# Architecture and scientific boundaries

<!-- Keep implementation details here; the execution plan owns live progress. -->

The project combines a persistent local supervisor with a Snakemake scientific
workflow. The hosted coding agent may inspect code, synthetic fixtures and
sanitised status, but patient-level evidence is interpreted only by local code
and authenticated loopback inference.

The inference client allows only its configured loopback health and completion
URLs. It explicitly disables environment-derived proxies and refuses every HTTP
redirect, so resumed jobs do not rely on inherited `NO_PROXY` settings. This
restriction applies to private inference, not the separate public-download
client. Python's [proxy and redirect handlers](https://docs.python.org/3/library/urllib.request.html)
are configured explicitly; synthetic tests check that request bodies and
credentials never follow a redirected destination.

## Data flow

```text
Pinned local model ──> phenotype review ──> Track 1 ranking ──> finalist review
                                                │                    │
                                                │              FASTQ acquisition
                                                │                    │
                                                └────────> CRAM/read validation
                                                                     │
Fixed public-source queries ──> evidence corpus ───────────────────────┤
                                                                     v
                                                       Local Track 2 synthesis
                                                                     │
                                                                     v
                                                   Private submission materials
```

Public queries come from `config/track2.yaml`, independently of patient results.
The corpus and patient-derived candidates are joined locally. Source responses
are evidence, not executable instructions. Search results and database metadata
are not promoted into biological proof.

## Code responsibilities

- `src/mva_runner/`: resource accounting, checkpoints, process ownership, local
  model review, report/workbook/video delivery, and publication audit.
- `src/mva_track1/`: private data handling, VCF/phenotype parsing, ranking,
  read support, submission schema and scientific provenance.
- `src/mva_track2/`: public-source collection and locally reviewed,
  evidence-linked repurposing hypotheses.
- `prompts/local/`: versioned local interpretation contracts. Their outputs
  require schema and source checks; they are not human reviews.

## Ordered scientific rules

`workflow/Snakefile` holds shared paths and includes these files. Numbering is
for navigation; the dependency graph determines which rules actually run.

| File in `workflow/rules/` | Responsibility |
|---|---|
| `00_targets.smk` | Public workflow targets |
| `10_inputs.smk` | Core-data and phenotype-review gates |
| `20_resources.smk` | Reference, annotation resources and BWA index |
| `30_annotation.smk` | Reference checks, normalisation and offline VEP |
| `40_prioritisation.smk` | Phenopacket, Exomiser and both ranking policies |
| `50_alignment.smk` | FASTQ QC and streaming duplicate-marked CRAM |
| `60_validation.smk` | Finalist intervals, read support and phase |
| `70_provenance.smk` | Initial and post-read provenance manifests |

Python-rule inputs explicitly track relevant scientific code and configuration.
Both the supervisor and Snakemake must invalidate stale results. Updating a
renderer alone must not trigger a new alignment. Alignment tracks the actual
sample/read-group value, not phenotype-review timestamps or finalist lists.

The BWA index uses `workflow/envs/bwa_index.yaml`, byte-preserved from its
original completed environment. Its legacy environment name and absence of
new comments inside that file are intentional: the scheduler fingerprints the
definition bytes. Read-QC/parser additions belong in `reads.yaml`. A separate
provenance rule checks all index/reference contig names, lengths and offsets,
hashes the five sidecars, records both solved toolchains, and requires identical
BWA executables before alignment. Its receipt enters final provenance; index
files are never outputs of that verification rule and cannot be deleted by its
failure cleanup. This does not claim a de novo reconstruction of the index.

## Coordinate, ranking and mechanism conventions

VCF positions remain 1-based GRCh38 coordinates. Chromosome alias conversion is
not liftover: reference lengths are checked where available and normalisation
checks each REF allele against the FASTA. VCF indels retain their anchor base.

Candidate pairs require evidence from both alleles. The current policy uses
the weaker allele for effect, technical and Exomiser components, excludes
same-locus artifacts and supported input-cis pairs, and preserves a genome-wide
comparison. `candidates_baseline.tsv` retains the earlier arithmetic and ordering.
Unresolved phase is not evidence of trans inheritance. Raw support and phase
are separate measurements; neither establishes causality.

The parser retains the selected transcript's `Feature`, `HGVSc` and `HGVSp`
together with its consequence, using the documented
[VEP output fields](https://www.ensembl.org/info/docs/tools/vep/vep_formats.html).
Selection remains the existing highest-impact annotation per gene, not an
exhaustive transcript-equivalence analysis. HGVS identifiers describe variants;
they do not establish functional effects.

Track 2 distinguishes unknown mechanisms, consequence-predicted loss of
function, and allele-linked functional literature supporting loss, gain or a
dominant-negative effect. Functional claims require a matching supplied allele,
gene, exact primary-source quote, assay, observed effect, reference context and
limitations, followed by local critique. Missense, gene knockout, pathway
proximity, or approval in another indication alone cannot establish the chain.
An empty retained-hypothesis list is a valid, explicitly reported result.

Raw-read QC is a separate screening layer. Packaging checks the exact FastQC
report inventory against the supplied FASTQ names, pinned tool version, all
default modules, archive CRCs and complete MultiQC HTML. Both track reports and
the private delivery manifest retain WARN/FAIL counts; valid files do not imply
that all modules passed. Composition flags do not establish their cause, and
the workflow does not trim reads merely to remove a flag. Library preparation,
detailed QC plots and candidate-level read evidence require separate review.
QC reporting changes invalidate packaging, not the measured alignment.

## Persistence and privacy

The supervisor owns a project lock and records PID plus process creation time.
A replacement supervisor adopts a verified surviving worker rather than
launching a duplicate. Atomic private checkpoints retain stage fingerprints,
outputs, attempts and technical error categories. Selected-stage completion is
not overall project completion or verification of code publication.

Finalist selection allows at most three local interpretation attempts. Rejected
answers and validation reasons are returned only to the local model, alongside
the unchanged original evidence. Candidate IDs and evidence field names are
schema-constrained; every cited value must exactly match its own candidate's
record. Code never substitutes a matching value to rescue a conclusion. The
attempt audit is private, and repeated rejection stops the stage. Transport
failures remain the supervisor's responsibility, not an interpretation retry.

The separate `provenance` stage owns the final scientific manifest. Report or
publication-code edits can refresh source hashes without invalidating the
measured reads or reserving alignment scratch space again. The manifest records
both ranking policies, ordered rule files, source modules, runtime configuration
and launchers alongside scientific inputs and solved environments.

All task caches, downloads, models, environments, scratch and outputs count
against the additional disk allowance. Owner-only private directories and logs
remain excluded from the explicit GitHub publication allowlist. See
[operations](02_operations.md) and [submission handoff](03_submission.md).
