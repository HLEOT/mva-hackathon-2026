# One-prompt completion of both MVA hackathon tracks

<!-- This is the approved execution guide. Keep progress and decisions current,
     and keep patient-level evidence, credentials, and private logs out of it. -->

Status: implementation in progress; scientific outputs are not yet complete.

Workspace: `/data/projects/mva-hackathon-2026`

Planning assessment date: 2026-09-05. Recheck operational facts before execution.

## How to use this file

Open the project checkout in your coding model and give it the prompt below,
or copy the equivalent prompt from [prompts/one_shot.md](../prompts/one_shot.md).
This file is the full execution contract: milestones, ordered file structure,
commenting requirements, acceptance checks, and recovery instructions.

The same prompt starts a new run or resumes an interrupted one. First reconcile
the recorded progress with current checkpoints and live process identities;
do not restart healthy jobs or repeat verified stages just because this document
contains an older status snapshot. Saving or reviewing this plan does not itself
start a scientific run.

## Prompt to give the implementation model

```text
Read AGENTS.md and docs/00_execution_plan.md completely. Implement or resume
the approved plan in /data/projects/mva-hackathon-2026. Treat the plan as the
execution guide and keep its progress, decisions, verification results, and
exact next action current. Reconcile checkpoints with live processes before
launching work; preserve healthy jobs and reuse verified completed stages.

Complete the software, run both hackathon tracks on the authorised local data,
generate and validate the submission materials, and create and upload the
audited code-only release to HLEOT/mva-hackathon-2026. Preserve the existing
staged work, environments, and reusable resources.

Publish small, focused, audited commits as coherent changes are ready; do not
wait for one bulk final commit. Check the destination branch before each write,
preserve remote changes, and verify each upload. Never force-push or include
unrelated staged files, secrets, source data, or patient-derived artifacts.

Use clear comments for a bioinformatician and the ordered file structure in
this plan. Work through the milestones without asking whether to continue.
Use up to 112 CPUs, 400 GiB RAM, and the available GPU, with no paid cloud
services. Enforce a combined limit of 250 GB additional disk usage beyond the
existing project footprint. Ask before exceeding that allowance.

Keep private interpretation local. Record automated reviews honestly, preserve
scientific uncertainty, and never invent evidence, credentials, approvals,
successful checks, or completion. Checkpoint long-running work and resume it
after interruptions. Continue independent work when another stage is blocked.

Ask only when a consequential ambiguity, missing credential, additional disk
allowance, or action beyond the approved scope prevents further progress.
Repository creation and code upload are already authorised. Challenge
submission and video hosting remain handoff actions.

Finish with verified artifact paths, the code repository URL, a concise account
of validation, and any remaining external handoff tasks. Do not stop at a
scaffold or a passing synthetic test suite when the real analysis remains.
```

## 1. Objective and accepted decisions

Turn the existing Track 1 foundation into a resumable workflow that completes
both MVA hackathon tracks, produces evidence-backed research outputs, packages
the submission materials, and publishes reproducible code.

Completion means validated local deliverables and a verified code release.
Leaderboard scoring and expert judging remain external outcomes. Do not equate
a plausible candidate, model-generated interpretation, or passing software
test with a confirmed causal variant or an effective treatment.

| Decision | Approved requirement |
|---|---|
| Scientific scope | Both Track 1 variant identification and Track 2 drug repurposing |
| Execution scope | Build, test, run the real analyses, package, and publish code |
| CPU limit | Up to 112 CPUs, accounting for concurrent processes |
| RAM limit | Up to 400 GiB, accounting for concurrent processes |
| GPU | Use the available local GPU where useful |
| Additional disk | At most 250 GB beyond the existing footprint; ask before exceeding it |
| Paid infrastructure | No paid cloud compute or paid APIs |
| Interpretation | Deterministic checks plus a local model; explicitly automated reviews |
| Pitch | Locally generated slides, timed script, synthetic narration, and MP4 |
| Hugging Face identity | Account `ErnieTn`, verified during planning; recheck before packaging |
| GitHub destination | Publish to public repository `HLEOT/mva-hackathon-2026`; create only if absent |
| GitHub contents | Code, documentation, configuration templates, and synthetic tests only |
| Commit cadence | Small, focused, audited commits as coherent changes are ready; no bulk-commit requirement |
| External handoff | Challenge submission and video hosting are not automatic |

The disk allowance is decimal: **250,000,000,000 additional bytes**. It includes
new downloads, environments, model weights, caches, temporary files, private
results, and delivery artifacts. Record a baseline before implementation and
account for task-created storage outside the project too. Do not evade the
allowance by moving temporary files elsewhere.

## 2. Verified starting point

These observations describe the planning assessment, not guarantees about a
future run:

- All **113 existing synthetic tests passed** using
  `.conda/launcher/bin/python -m pytest -q`.
- All five environments reported ready: scheduler/launcher, launcher rule,
  HTS rule, annotation rule, and read-validation rule environments.
- Core data and its manifest, the private phenotype draft, GRCh38 reference,
  BWA-MEM2 index, VEP merged cache, and Exomiser resources reported ready.
- Reviewed phenotype configuration, ranking, reviewed finalists, read
  validation, final run manifest, and submission identity remained incomplete.
- The public-resource Snakemake dry run had no pending jobs. It warned of
  missing provenance metadata for three resource-installation rules. Validate
  and record existing resources; do not blindly redownload them or fabricate
  completion markers.
- Approximately 166 GB of public resources and 6.1 GB of environments were
  present. The eight remaining FASTQs total **84,668,434,104 bytes (84.67 GB)**.
- The host exposed 128 CPUs, about 503 GiB RAM, a roughly 96 GB NVIDIA RTX PRO
  6000 Blackwell GPU, and 2.8 TB free disk. Available physical space does not
  increase the authorised 250 GB allowance.
- The installed CUDA compiler reported version 12.0. Check compatibility with
  Blackwell before selecting or installing the local inference runtime.
- The repository had 45 staged files, no commits, and no Git remote. These
  staged files are the user's existing work and must be preserved.
- The connected GitHub account was `HLEOT`. The proposed repository returned
  not found. The connector did not expose repository creation, and the shell
  lacked GitHub CLI authentication.

## 3. Implementation milestones

### Milestone 1: Execution contract and baseline

Create the agent instruction file and reusable prompt from this guide. Record
the current source state, resource inventory, storage baseline, and applicable
hackathon requirements. Preserve existing files and valid resources. Keep this
document self-contained as implementation progresses.

Maintain a progress checklist, decision log, verification record, blockers,
and exact next action. Only non-sensitive operational summaries belong in
tracked documentation; private evidence and detailed logs stay in ignored
locations.

### Milestone 2: Unified launcher and persistent execution

Introduce `./mva` with these interfaces:

```bash
# Check configuration, authentication, resources, and the storage allowance.
./mva preflight

# Execute both tracks and reuse verified completed stages.
./mva run --tracks both --resume

# Return machine-readable progress without private scientific content.
./mva status --json

# Validate and construct the local deliverables.
./mva package

# Stop the supervised run cleanly, retaining recoverable progress.
./mva stop
```

Keep `./mva-track1` compatible. Use Snakemake for scientific dependencies and
a small supervisor for persistent execution, resource accounting, retries,
and completion validation. Run the supervisor in a named `tmux` session so a
terminal disconnect does not terminate healthy analysis jobs.

Persist atomic checkpoints containing stage state, attempts, process identity,
heartbeat, input/configuration hashes, and artifact validation outcomes. Resume
verified stages after interruption and invalidate downstream outputs when
their inputs change. Prevent duplicate launches. Retry transient failures with
backoff, continue independent work where possible, and expose actionable
summaries for persistent failures.

A persistent analysis process does not guarantee an indefinitely active coding
model. Keep sufficient progress on disk to resume the exact coding session or
continue from this plan after session or service limits interrupt it. Do not
weaken permissions or bypass service limits to prolong execution.

### Milestone 3: Complete and strengthen Track 1

Replace placeholder reviews with explicitly recorded automated reviews.
Validate HPO terms against a pinned ontology, retain source evidence locally,
and preserve uncertain or conflicting assertions. Automated interpretation
must not masquerade as a human review.

Test real VEP-Exomiser integration and allele matching. Strengthen candidate
handling for inheritance, evidence supporting both members of a pair,
same-locus artifacts, and phase. Preserve a genome-wide comparison so
known-gene prioritisation cannot conceal stronger alternatives. Retain
unresolved phase honestly and reassess finalists after read validation.

Reuse the existing GRCh38 and annotation resources after validation. Retain
the baseline ranking as a documented comparator when changing scientific
ranking behaviour. Explain material changes and their biological rationale.

### Milestone 4: Raw-read validation within the storage allowance

Plan each large stage against both available disk and the remaining additional
allowance. Include partial downloads, extraction overhead, cache duplication,
alignment scratch space, and final output overlap in estimates.

The FASTQs consume 84.67 GB before alignment. Avoid duplicate download caches,
stream duplicate-marked alignment output into CRAM instead of retaining a
complete intermediate BAM, and account for threads and RAM across concurrent
pipeline processes. Align once and reuse the verified CRAM when finalists
change. Clean only identified, regenerable task-owned temporary artifacts once
their downstream outputs are verified.

Monitor storage during execution. Pause before exceeding the authorised
allowance and report the additional space required. Do not delete existing
user resources or source data to avoid requesting more space.

### Milestone 5: Local interpretation

Default to the approximately 18.6 GB Qwen3-30B-A3B `Q4_K_M` model through a
pinned llama.cpp runtime. Record the exact model revision, checksum, runtime,
inference parameters, and prompt versions. Verify GPU/runtime compatibility
with a synthetic smoke test before downloading large additional dependencies.

Bind inference locally with authentication. Keep private prompts, responses,
and logs owner-readable and Git-ignored. Do not send phenotype text, variants,
genotypes, or patient-derived interpretation prompts to hosted models.

Require structured responses referencing supplied evidence and validate their
contents. Retain uncertain conclusions as uncertain. Model output must not
substitute for measured read support, confirmed phase, verified approval
status, or sourced biological evidence.

### Milestone 6: Track 2 evidence and repurposing workflow

Create versioned public evidence collections covering MVA biology, pathways,
drug mechanisms, approval status, safety information, and primary literature.
Use Reactome, ChEMBL, PubMed/PMC, and official regulatory sources. Record source
identifiers, retrieval dates, versions where available, and checksums.

Acquire public knowledge independently of private patient content, then join
it to Track 1 results locally. Avoid placing patient-derived evidence in
external queries or hosted-model prompts.

For each proposed drug, record the hypothesised variant mechanism, intervention
direction, supporting and opposing evidence, approval jurisdiction,
limitations, and proposed experimental validation. Distinguish direct evidence
from pathway-based inference. Network proximity alone is insufficient to
establish a therapeutic rationale.

Select up to five defensible hypotheses. Do not fill the list with unsupported
candidates, infer gain or loss of function without evidence, or describe an
unvalidated hypothesis as an effective treatment. Explicitly report an absence
of sufficiently supported candidates if that is what the analysis finds.

The Track 2 report must explain how variant mechanism supports the repurposing
rationale and address scientific rigor, potential impact, innovation, and
scalability.

### Milestone 7: Submission materials and code release

Generate the following local deliverables:

- Track 1 CSV validated against the current official schema, with at most ten
  rows, GRCh38 coordinates, and explicit ranking and uncertainty.
- Track 1 and Track 2 reports in Markdown and PDF.
- Completed methods-description workbooks using the official template.
- Final provenance manifests and a readable submission/handoff checklist.
- Pitch slides, a timed script, local synthetic narration, and an MP4 lasting
  no more than 180 seconds, using local speech synthesis and FFmpeg.

Include the required acknowledgement, current dataset citation, actual AI
usage, and verified data-handling details. Inspect rendered reports and video;
file existence alone is not acceptance. Keep scientific outputs and the
generated submission bundle local.

Audit an explicit allowlist of code, documentation, public configuration
templates, and synthetic tests. Exclude source data, private settings,
credentials, patient-derived outputs, model weights, environments, caches,
and logs. Do not use an indiscriminate staging command for publication.

Create the public repository `HLEOT/mva-hackathon-2026`, push the audited code,
and verify its remote contents. Recheck repository existence first; if a
repository now exists, establish that it is the intended destination and
preserve its existing content. Include the canonical repository URL in both
reports. Repository creation and code upload are already authorised.

Publish incrementally throughout the milestones; publication is not reserved
for the final packaging stage. Each commit should contain one coherent change
with an accurate message and relevant checks. Documentation-only commits need
document/link checks; code commits need the appropriate tests. Inspect the exact
files and diff before every upload, re-read the remote branch to avoid overwriting
concurrent work, and verify the resulting commit and file contents afterward.
Do not force-push or include unrelated entries from the user's staged index.
An intermediate commit is a progress checkpoint, not proof that the project is
complete. Record final release verification separately from incremental uploads.

If repository-creation authentication is missing, prepare all independent
work and request the necessary login without asking for the token in chat.
The GitHub connector being authenticated does not automatically provide shell
credentials or a repository-creation capability.

Leave challenge submission and video hosting as explicit final handoff tasks.
Recheck the current rules before finalising materials and document data
lifecycle obligations without automatically deleting data or sending messages.

## 4. Ordered file structure and commenting standard

Retain established data locations and the Track 1 package. Organise additions
as follows. Entries other than this guide may still need to be implemented.

```text
mva-hackathon-2026/
├── README.md                       # Purpose, quick start, outputs
├── AGENTS.md                       # Scope, persistence, verification rules
├── mva                             # Unified launcher
├── mva-track1                      # Existing compatible launcher
├── pyproject.toml
├── config/
│   ├── config.yaml                 # Commented Track 1 settings
│   ├── execution.yaml              # Compute, disk, retries, local model
│   ├── track2.yaml                 # Public sources and evidence policy
│   └── *.local.*                   # Ignored credentials/private settings
├── docs/
│   ├── 00_execution_plan.md         # Current milestones and recovery state
│   ├── 01_architecture.md           # Data flow and scientific assumptions
│   ├── 02_operations.md             # Launch, monitor, resume, troubleshoot
│   └── 03_submission.md             # Current requirements and handoff
├── prompts/
│   ├── one_shot.md                  # Single implementation/execution prompt
│   └── local/                      # Versioned interpretation templates
├── src/
│   ├── mva_runner/                 # Supervisor and resource accounting
│   ├── mva_track1/                 # Existing variant workflow
│   └── mva_track2/                 # Evidence and repurposing workflow
├── workflow/
│   ├── Snakefile
│   ├── rules/                      # Numbered stages in execution order
│   └── envs/                       # Pinned stage environments
├── tests/                          # Synthetic unit/integration/recovery tests
├── resources/public/               # Ignored reference/evidence/model caches
├── data/gated/                     # Ignored source data
├── work/private/                   # Ignored scratch, checkpoints, inference
├── results/private/                # Ignored evidence and final analyses
├── submissions/                    # Ignored reports, CSV, workbook, video
└── logs/                           # Ignored operational logs
```

Write comments for a bioinformatician. Explain biological assumptions,
coordinate conventions, units, thresholds, uncertainty, and recovery behaviour
instead of merely repeating the code. Document the inputs and outputs of
substantial functions and workflow stages.

Convert the current JSON-formatted `.yaml` files to commented YAML, while
retaining compatibility with existing JSON-formatted local configurations.
Use safe parsing and include the required parser in every environment that
loads these configurations.

## 5. Verification and acceptance

- Preserve the passing baseline and add meaningful integration tests using
  synthetic variants, phenotype text, reads, and drug evidence.
- Test interrupted downloads, restart recovery, stale artifacts, duplicate
  launches, unavailable sources, malformed model responses, and disk-budget
  enforcement.
- Test ambiguous phenotype assertions, unresolved/cis phase, weak second
  alleles, unsupported drug mechanisms, and contradictory evidence.
- Verify that private records and credentials cannot enter hosted-model
  requests, public logs, or the GitHub release.
- Complete the actual local analyses. Validate the official CSV schema,
  inspect report rendering, check workbook completeness, and measure the
  video duration.
- Confirm that the published code can reproduce the synthetic demonstration
  from a clean environment.
- Verify final provenance, artifact integrity, and the uploaded code contents.
  Mark unresolved scientific conclusions explicitly.

Declare overall completion only after required artifacts pass validation and
the code upload is verified. Record challenge submission and video hosting as
external handoff items, not as completed actions.

There is no artificial short wall-clock limit. Healthy jobs continue until
completion. Missing authentication, persistent technical failures, and a need
to exceed the disk allowance produce saved, recoverable blockers rather than
repeated identical attempts or fabricated success. Do not stop merely because
a large job is still running or because a synthetic test suite passes.

## 6. Progress and recovery record

<!-- Update these sections at each milestone or interruption. Keep detailed
     scientific evidence in ignored private files, not in this public guide. -->

- [x] Repository and runtime assessed; existing synthetic tests passed.
- [x] User approved both tracks, local automated interpretation, narrated
  video, resource limits, and code-only GitHub publication.
- [x] Approved plan saved as a Markdown execution guide.
- [x] Milestone 1: execution contract and baseline.
- [ ] Milestone 2: unified launcher and persistent execution.
- [ ] Milestone 3: complete and strengthen Track 1.
- [ ] Milestone 4: raw-read validation within the storage allowance.
- [ ] Milestone 5: local interpretation.
- [ ] Milestone 6: Track 2 evidence and repurposing workflow.
- [ ] Milestone 7: submission materials and code release.
- [ ] Full acceptance checks and final handoff.

### Decision log

- 2026-09-05: Use the existing project as the baseline and extend it to both
  tracks; preserve staged code and valid downloaded resources.
- 2026-09-05: Use maximum practical local compute with a hard allowance of
  250 GB additional disk usage; ask before exceeding it.
- 2026-09-05: Use deterministic checks plus local inference and generate a
  narrated pitch locally.
- 2026-09-05: Create `HLEOT/mva-hackathon-2026` and upload code, not the large
  data or generated analysis artifacts.
- 2026-09-05: The user explicitly permits incremental GitHub publication.
  Publish coherent, audited changes as they become ready instead of waiting
  for a single bulk commit; preserve the existing local index and remote work.

### Verification record

Scientific entries below are the last recorded execution snapshot, not a live
status report. Revalidate them before choosing the next stage.

- Planning baseline: 113 synthetic tests passed.
- Planning baseline: public-resource dry run required no jobs; missing
  installation provenance metadata was noted above.
- Implementation verification: 137 synthetic tests passed on 2026-09-05.
- Implementation verification: 187 synthetic tests passed after ordered-rule,
  live-process recovery, publication-race, HGVS/functional-evidence and shorter
  PDF re-render tests. The real prioritisation dry run parses all 26 rules and
  schedules source-invalidated outputs; no rerun triggers were suppressed.
- Implementation verification: 198 synthetic tests passed after bounded
  authentication preflight and separation of provenance refresh from expensive
  read-validation checkpoints. All five scientific environments are ready.
- Implementation verification: 223 synthetic tests passed after upstream
  template integrity/freshness checks, live code-release verification,
  source-linked FDA salt identities with combination-product exclusion, and
  conservative complex-allele/indel read support. These tests do not substitute
  for the pending real read analysis. Insertions require a matching anchor and
  adequate inserted-base qualities; unmodelled representations cannot create
  direct fragment-phase evidence, and unmatched indels remain inconclusive.
- Local inference: pinned model and runtime checksums verified; NVIDIA Vulkan
  discovery and structured synthetic inference passed. Loopback authentication
  is configured; private prompts and responses remain local.
- Real phenotype review: completed with pinned HPO v2026-09-01, exact source
  anchors, explicit automated review, and uncertain features excluded from scoring.
- Real integration found bare VCF chromosome names versus chr-prefixed reference
  names. Added length-checked alias mapping before REF-checked normalisation;
  the synthetic alias/mismatched-length regression test passed.
- Public Track 2 collection: 96 literature records; all 16 ChEMBL, 32 Entrez,
  10 FDA and 7 corrected Reactome requests succeeded. Full raw responses,
  retrieval metadata, checksums and bounded-search limitations are retained.
- Official methods workbook and current challenge sources were downloaded at a
  pinned Space revision. Local FFmpeg and verified speech runtime are installed.
- The initial real annotation/prioritisation completed; source changes require
  a refresh. Final scientific and delivery acceptance checks have not passed.
- Documentation handoff check, 2026-09-05: the intended public GitHub repository
  exists and the connected account has push access. The remote had no branch
  heads when checked before the first documentation upload.
- Documentation published and bytes verified in commits `378ebef` and `ea573c5`;
  the original 45-entry staged index was preserved.
- Code checkpoint `1c17d4b` published 95 audited files (470,834 bytes). A fresh
  public clone matched every audited path, blob and executable mode. Its 187
  tests passed in a new Python virtual environment with no system-site-packages;
  dependency checks passed. This uses host Poppler/fonts, not a clean OS image.
  Later changes require their own publication and reproduction verification.
- Code checkpoint `3f65233` added preflight and provenance isolation. All 97
  remote files/modes matched the privacy audit, the original staged index was
  unchanged, and 198 tests passed in the same isolated reproduction environment
  after updating its public checkout. Generated editable-install metadata was
  preserved rather than discarded.
- At 18:38 UTC, all seven official source/template files matched their upstream
  Git/LFS digests at Space revision `1c761cc23d90aebe6a011fd5b0b99517df42408c`;
  the live head had no selected-source changes. The public Synapse wiki tree
  contained only the inspected landing wiki (last modified 2026-08-24), with no
  citation/DOI reference found. The project-level citation remains provisional;
  no formal reference or DOI has been invented.
- Live execution check at 18:24 UTC: the read-download supervisor and child
  were verified alive; additional storage was 76.88 GB of the 250 GB allowance.
  A separate private controller was then started for the required prioritisation
  refresh, with 16 CPUs inside the existing 112-CPU affinity, aggregate memory
  and disk guards, private logs and its own PID/start-time receipt. It does not
  mutate main supervisor state. Wait for both owned jobs before full resumption.

### Blockers and prerequisites

- GitHub repository creation is no longer a prerequisite: the intended public
  repository and connected write access have been verified. Check the remote
  branch before each incremental upload and record the verified release commit.
- The user has been asked asynchronously for the hosted coding account's plan
  and data-sharing setting, required for an accurate methods disclosure.
- A formal dataset citation was not located on the current Synapse page or its
  wiki tree. The local report uses an explicitly provisional project reference;
  obtain organiser confirmation before claiming full citation compliance.
- Estimate and monitor peak additional disk usage before large downloads or
  alignment; ask if the approved 250 GB allowance is insufficient.

### Exact next action

On the next execution turn, run ./mva status --json and reconcile the private
checkpoints with live process identities, including the one-off refresh receipt
at work/private/runner/prioritise_refresh_state.json. Resume from the first
incomplete or invalid stage after both jobs finish; do not restart a healthy
process based on historical status above. Finish remaining recovery/acceptance tests, raw-read validation, local
Track 2 synthesis, and packaging as their prerequisites become ready. Publish
coherent audited changes incrementally and verify the final code release.

### Outcomes and remaining work

Instructions, prompt versions, commented YAML, storage accounting, a persistent
runner, private review, both track implementations and stronger candidate gates
are implemented. The immutable baseline is 184,345,051,136 bytes. The original
45-entry staged index is preserved and checkpointed privately. Streaming CRAM
and immutable pre-read proposals prevent full BAM overlap and unnecessary
realignment when the shortlist changes. Real phenotype review and public
evidence acquisition are complete. A tested, code-only checkpoint is public.
Full real analyses, final deliverables, remaining recovery/acceptance tests and
final code-release verification are outstanding.

## 7. Reference sources

The following public sources informed the plan. Recheck mutable requirements
before submission and record the versions used during implementation.

- [Official hackathon application](https://sagebio-rare-disease-real-kid-mva-hackathon-2026.hf.space/)
- [Official Track 1 instructions](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/blob/main/tabs/submit_track1.py)
- [Official Track 2 instructions](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/blob/main/tabs/submit_track2.py)
- [Official rules](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/blob/main/tabs/rules.py)
- [Official clarification of provider terms and data handling](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/discussions/2)
- [Official submission templates](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/tree/main/static/templates)
- [OpenAI guidance on persistent execution plans](https://developers.openai.com/cookbook/articles/codex_exec_plans)
- [OpenAI prompting guidance: outcomes, context, and boundaries](https://learn.chatgpt.com/docs/prompting)
- [OpenAI guidance on non-interactive session resumption](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Qwen3-30B-A3B model and quantisations](https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF)
- [llama.cpp build documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)
- [samtools sort documentation](https://www.htslib.org/doc/samtools-sort.html)
- [samtools markdup documentation](https://www.htslib.org/doc/samtools-markdup.html)
- [Reactome Content Service](https://reactome.org/dev/content-service)
- [ChEMBL data services](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services)
- [DailyMed web services](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)
