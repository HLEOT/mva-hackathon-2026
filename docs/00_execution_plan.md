# Execution plan: Codex analysis, PC computation

<!-- This is the current contract and compact handoff. Keep decisions, progress,
     verification and the exact next action current; keep verbose logs private. -->

## 1. Outcome and current direction

Complete both tracks of the Rare Disease, Real Kid: MVA Hackathon 2026 using
authorised challenge data, reproducible local computation, evidence-grounded
interpretation, and independently checked submission materials. Software tests
alone are not scientific completion. A ranked hypothesis is not a diagnosis;
an experimental drug hypothesis is not a treatment recommendation.

**Codex in this conversation directs and interprets the analysis. Scientific
programs run on this PC. There is no separate downloaded LLM, inference server,
nested coding agent, or workflow-owned hosted AI API.** The user explicitly
rejected the earlier local-model architecture on 2026-09-06.

Use [the one-prompt handoff](../prompts/one_shot.md) to start or resume this plan.
Persist checkpoints and continue useful independent work through interruptions.
A prompt cannot remove service limits or guarantee an indefinitely active Codex
session. Long scientific workers run in tmux; interpretation waits for Codex.

## 2. Authority, privacy and resource limits

- Preserve the user's original staged index and unrelated work. Code-only
  publication to `HLEOT/mva-hackathon-2026` is authorised in focused commits.
  Audit every path, preserve remote changes, verify uploads, never force-push.
- Use at most 112 CPUs, 400 GiB RAM and 400,000,000,000 additional allocated
  bytes beyond the immutable 184,345,051,136-byte baseline. Keep a 10 GB reserve
  and check filesystem free space too. Do not reset the baseline after cleanup.
- Keep task environments, downloads, caches and scratch inside this checkout.
  Existing hardware and Codex access are used; do not purchase cloud compute.
- Codex with local tool execution is not necessarily local model inference.
  Before private case evidence enters this conversation, confirm the actual
  account terms meet the organiser's no-training/no-rights and limited-retention
  requirements. Until then use public code, public sources, synthetic fixtures
  and sanitised technical status. Do not infer settings or read credentials to
  guess a subscription. See [the organiser's clarification](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/discussions/2).
- `config/ai_usage.local.yaml` records the existing Codex account's `hosted_plan`
  and `hosted_data_setting`, plus explicitly confirmed booleans
  `private_codex_review_authorized` and `provider_terms_confirmed`. These are
  evidence of permission and methods disclosure, not a new account purchase.
  Never fill them speculatively or turn them on to bypass a gate.
- Never expose gated data, private outputs or credentials on GitHub. Challenge
  submission, video hosting and required lifecycle communications remain user
  handoff actions. Routine safe local cleanup is already authorised.

## 3. Ordered structure and commenting standard

```text
AGENTS.md                         Project-wide instructions
README.md                         Entry points and short setup
docs/
  00_execution_plan.md            Current contract, progress and next action
  01_architecture.md              Scientific design and evidence boundaries
  02_operations.md                Run, review, recover and clean up
  03_submission.md                Deliverables and external handoff
prompts/
  one_shot.md                     Copy-and-paste Codex handoff
  review/                        Phenotype, finalist and Track 2 review guides
config/                          Commented public configuration; ignored secrets
src/
  mva_runner/                    Supervisor, Codex checkpoints, cleanup, delivery
  mva_track1/                    Parsing, annotation, ranking and read validation
  mva_track2/                    Public evidence and repurposing evidence gates
workflow/
  Snakefile                      Shared scientific dependency graph
  rules/00_targets.smk ...        Ordered rules through 70_provenance.smk
  envs/                          Pinned scientific environment definitions
tests/                           Synthetic fixtures and regression tests
data/gated/                      Ignored authorised source data
resources/public/                Ignored installed references and public evidence
work/private/                    Checkpoints, reviews, scratch and audit history
results/private/                 Scientific evidence tables and provenance
submissions/                     Private reports, CSV, workbooks and pitch
```

Comment biological assumptions, reference/coordinate conventions, units,
evidence thresholds, failure recovery and cleanup prerequisites for a
bioinformatician. Avoid gratuitous abstractions, duplicate scripts and stale
operational diaries. Preserve the original BWA index environment bytes: editing
that definition unnecessarily can trigger expensive reindexing.

## 4. Execution and acceptance milestones

1. **Preflight and reuse.** Verify inputs, pinned resource manifests, account
   access where needed, storage, tool availability and live process identities.
   Match PID and creation time; never restart a healthy or paused worker merely
   because a tool wait timed out. Reuse verified completed resources and CRAM.
2. **Phenotype review.** Local code prepares a bounded, numbered-source request.
   Codex returns structured present/absent/uncertain assertions. Local gates
   require active pinned HPO terms, exact quotes and conservative handling of
   negation, family history, conflicts and uncertain semantic mappings.
3. **Track 1 computation.** Verify GRCh38 contig-length aliases and REF alleles;
   normalise/split with bcftools; run offline merged VEP and compatible Exomiser.
   Compare genome-wide ranking with the historical known-gene-prioritised policy.
   Both alleles must support a pair; exclude same-locus artifacts and observed
   cis pairs. Retain uncertainty about phase, causality and non-coding coverage.
4. **Finalist review and raw-read validation.** Codex selects 1–10 supplied
   candidates using exact evidence fields, rationale and uncertainty. Download
   only missing bytes, perform FastQC/MultiQC, stream alignment into CRAM once,
   measure read support and phase, then reassess. Archive exact pre-reassessment
   measurements and decisions before replacing working tables. Keep real QC
   WARN/FAIL flags; a valid artifact is not an all-module PASS claim.
5. **Track 2.** Acquire public evidence using fixed patient-independent queries.
   Codex examines bounded source records alongside permitted case evidence.
   Require correct compound identity, regulatory evidence, variant mechanism,
   exact source anchors, primary functional evidence where claimed, safety,
   opposing evidence and a falsifiable experiment. A second Codex critique is
   not independent biological validation. Zero retained hypotheses is valid.
6. **Delivery.** Require genuine current Codex review receipts, full scientific
   integrity, current official rules/templates, truthful AI disclosure, dataset
   citation and acknowledgement. Build both reports in Markdown/PDF, the
   official Track 1 CSV, two methods workbooks, slides/script and locally narrated
   MP4 at most 180 seconds. Verify PDF layout, workbook completeness, CSV schema,
   artifact hashes, video streams/duration and a strict full decode.
7. **Release and handoff.** Publish coherent audited code increments, then verify
   the final public tree and reproduce synthetic tests in an isolated environment.
   Document real artifact paths and remaining user actions. Do not claim clinical
   validation, successful submission or overall completion from draft files.

Local workers checkpoint with `awaiting_codex_review` when interpretation or
confirmed provider terms are missing. They do not download a replacement model,
call a hosted API, invent answers, or endlessly retry a review. Codex resumes
the relevant stage after supplying an actual exact-input response. See the
response format and recovery steps in [operations](02_operations.md).

## 5. Space-aware operation

The user authorises autonomous deletion/compaction of unnecessary task files.
Use `./mva cleanup` to inspect and `./mva cleanup --apply` to remove known
disposable caches and obsolete synthetic rendering scratch while idle. This
narrow cleanup is also enabled between stages. `--compact-resources` verifies
installed resources and removes redundant installation archives; retain URLs,
original digests and installed-file verification manifests.

Budget peak growth before each large stage and monitor it while running. Count
partial downloads, extraction overlap, environments, temporary sort runs and
outputs. Reuse valid data rather than copying or recomputing it. Do not recompress
FASTQ.gz, VCF.gz, CRAM, indexed databases or already-compressed caches. Do not
hard-link independent mutable outputs or remove package-cache files that active
environments depend on. Unknown or unique scratch is not automatically disposable.

Cleanup must resolve exact targets, refuse symlinks and live workers, journal
deletions, and report reclaimed allocated bytes. Do not remove source data,
expensive verified results, scientific decision trails or current deliverables.
Do not retain another giant backup of a reproducibly downloadable archive.

## 6. Progress, decisions and next action

- Previous execution completed both scientific lanes and checked a 12-artifact
  private draft, including a 138.129313-second pitch. It used the now-rejected
  local model. Those reviews are **historical, not Codex reviews**, and no final
  challenge submission was made. Detailed evidence stays in private receipts.
- 2026-09-06: user changed interpretation to Codex here and requested autonomous
  space-aware cleanup. The owned model server was stopped, its weights/runtime
  and obsolete token removed, and small provenance archived privately. Source
  data, installed scientific tools, completed CRAM and prior evidence remain.
- Implemented Codex review checkpoints, removed the inference client/model stage,
  added safe cleanup and archive compaction with installed-file integrity checks.
  All 295 synthetic tests passed, including an actual worker review-pause test,
  cleanup refusal tests, compacted-resource corruption and reinstall recovery.
- Cleanup reclaimed approximately 86.3 GB. Exomiser's installed files passed an
  independent full SHA-256 check after compaction; VEP passed its installed
  metadata/shard/index inventory checks. Offline preflight confirms all base
  scientific resources remain ready; authentication is deliberately unverified
  offline and final scientific provenance needs refresh for the changed code.
  The original 45-entry staged index remains byte-identical. Public release
  verification and isolated reproduction are recorded under work/private/runner.
- Code release `7525ce6` was verified against all 111 audited files and modes;
  all 295 tests and the dependency check passed in the isolated Python checkout.
  Later documentation-only checkpoints retain the same tested implementation;
  use the private release receipts for the exact current public commit.
- Current scientific outputs must not be relabelled or packaged as Codex-reviewed.
  New review gates require actual responses and confirmed data-use terms. Dataset
  citation and final methods disclosures still require truthful confirmation.
- On goal resumption, live preflight verified authorised dataset access, the
  public code destination and all base scientific resources. No scientific
  worker remains live. Storage is approximately 43.5 GB above the unchanged
  baseline. The remaining private-review prerequisite is factual confirmation
  of the Codex account's applicable provider terms; repeated compute cannot
  supply that information. See work/private/runner/codex_goal_resumption_audit.json.

**Exact next action:** the architecture change and storage cleanup are complete.
Respect the actual goal status: when active, continue safe independent work;
when paused, do not resume the full analysis. Do not restart historical alignment,
watcher or recovery jobs. Before new private interpretation, obtain actual
provider-terms confirmation. Once execution is active and those terms are confirmed,
use `./mva run --tracks both --resume`, handle `./mva reviews` in this Codex
session, preserve all previous attribution, and refresh only affected science
and delivery dependencies. Never fabricate checkpoints to conceal stale results.

## 7. Reference sources

- [Official hackathon application](https://sagebio-rare-disease-real-kid-mva-hackathon-2026.hf.space/)
- [Official rules](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/blob/main/tabs/rules.py)
- [Official templates](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/tree/main/static/templates)
- [Provider terms and data handling](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/discussions/2)
- [Codex local code execution](https://learn.chatgpt.com/docs/codex/cli)
- [Codex authentication and applicable data policies](https://learn.chatgpt.com/docs/auth)
