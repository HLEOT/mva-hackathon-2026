# Operations, monitoring and recovery

<!-- Never paste private log contents into hosted chats or public issues. -->

Run commands from `/data/projects/mva-hackathon-2026`. The `mva` launcher sets
owner-only permissions and project-local cache/temp locations. Its Python is
`.conda/launcher/bin/python`. Use `./mva-track1 bootstrap` only when the launcher
environment is missing; preserve valid existing installations.

## Normal operation

```bash
# Inspect prerequisites, resource limits and storage before large work.
./mva preflight

# Run both local scientific tracks and package their outputs in tmux.
./mva run --tracks both --resume

# Observe technical state without printing patient evidence.
./mva status --json

# Stop the owned supervisor or recover a verified orphaned stage group.
./mva stop

# Resume later with the same command; verified checkpoints are reused.
./mva run --tracks both --resume
```

Do not launch a second run when `supervisor_live` or a recorded `child_live` is
true. An observation timeout is not a failed analysis. Check process identity,
heartbeat and storage changes before deciding that work is stalled. Never
kill a process by an unverified PID or a broad command-name match.

`child_live` includes an OS-paused process. Check `child_paused` and the top-level
`paused_stages` list too: a supervisor heartbeat is not proof of active
computation. These fields inspect PID/start-time and kernel process state;
they do not signal a worker or authorise its resumption.

`--stages` selects a stage plus all its prerequisites, for example
`./mva run --resume --stages download_reads`. Inspect `selected_stages` in the
status response: `complete` applies to that selection, not the entire project.
`--tracks track1` is a scientific-only subset ending at read validation and
provenance; it does
not collect Track 2 evidence or build the unified two-track package.

`./mva package` runs the two-track packaging dependency chain in the foreground.
For unattended work, prefer the persistent full `run` command. The original
`mva-track1` CLI remains available for its documented Track 1 workflow.

## Resource and storage contract

Preflight performs bounded identity and gated-file metadata checks, reports
scientific resource readiness, checks the owned local model, and lists missing
delivery tools/disclosures. It never sends patient content or prints credentials.
`--offline` skips network checks and leaves authentication unverified; it does
not turn token presence into evidence of access. Missing future outputs do not
block independent earlier stages. Execution rejects limits beyond the approved
contract even when preflight was skipped.

The host must supply `tmux`, `pdftotext` and `pdftoppm` (Poppler). PDF tests and
delivery use those local executables. The delivery environment supplies FFmpeg;
the verified local speech runtime is recorded separately. A clean Python
environment alone does not supply these operating-system tools.

- Use no more than 112 CPUs and 400 GiB RAM across concurrent work.
- The additional allowance is 400,000,000,000 decimal bytes, explicitly approved
  on 2026-09-05, not free space on the host and not 400 GiB. The stored baseline
  must never be increased to conceal task growth.
- A 10,000,000,000-byte reserve covers in-flight writes during a clean stop.
- Include partial downloads, environments, model weights, caches, extraction
  overlap, sort buffers and outputs in stage estimates.
- If a budget gate stops work, save the exact request and ask before increasing
  the allowance. Do not delete source data or user resources to evade it.

The eight FASTQs require 84,668,434,104 bytes. Alignment streams through name
sorting, fixmate, coordinate sorting and duplicate marking into CRAM; it does
not retain a complete intermediate BAM. Thread allocation accounts for each
samtools main process and its additional `-@` workers. Reuse the validated CRAM
when a shortlist changes.

Streaming does not eliminate temporary-file overlap: the two sorts may retain
their own BAM runs simultaneously before final merge cleanup. Budget that
overlap as well as the final CRAM; the behaviour is visible in the pinned
[samtools 1.22 sorting implementation](https://github.com/samtools/samtools/blob/1.22/bam_sort.c).

For the now-completed alignment, a private one-off watcher ran in tmux
session `mva-budget-watch-400gb` to preserve process memory when storage was tight.
Its receipt is `work/private/runner/alignment_budget_watch_state.json`; verify
its controller PID/start-time as well as the recorded stage owner. It pauses
only that validated session/process group when remaining headroom reaches
20 GB, ahead of the main supervisor's 10 GB reserve. It never raises the 400 GB
allowance, rewrites main supervisor state, deletes files or resumes automatically.
This is a live-run recovery aid, not a requirement for a fresh public checkout.
The initial 250 GB watcher was retained until the explicit 400 GB approval.
It was then replaced after identity checks, and the same alignment group was
continued without a restart. The original pause remains recorded in
`work/private/runner/paused_alignment_checkpoint.json`; approval and replacement
details are in `work/private/runner/disk_allowance_400gb_approval.json`. The
current watch receipt tracks the replacement controller, not the retired one.
Both the alignment and watcher have since finished. Treat these receipts as
historical recovery evidence, not instructions to restart the watcher or signal
the original worker. Reuse the independently verified CRAM and index.

If that receipt reports a verified pause, do not start another supervisor.
After an explicit storage decision, reconcile the approved contract and
configuration first. Stop only the verified watcher controller if its old
hard-coded allowance is being replaced; stopping it does not resume the worker.
Then verify the saved stage/group/member identities and current scientific
inputs before an explicit continuation of that same paused group. If the
worker has exited instead, use normal checkpoint recovery rather than signalling
a stale PID. A deliberate `./mva stop` can terminate a paused group; its
in-memory progress is not a durable on-disk checkpoint.

## Credentials, inference and failure handling

Store the authorised Hugging Face read token only in the owner-readable,
ignored `config/hf_token.local.txt` or process environment. Never paste it into
chat or commit it. `config/model_token.local.txt` is for the owned loopback
inference server, not a hosted endpoint.

Private logs are under `logs/`; state, worker receipts and local inference
records are under `work/private/`. Inspect scientific failures using local
parsers and expose only sanitised categories/counts to the coding conversation.
Use synthetic fixtures to reproduce parser or schema errors.

Transient transport failures and HTTP 429/5xx may retry with bounded backoff.
Authentication failures, invalid evidence, unsupported mechanisms and disk
limits are not solved by identical retries. Preserve completed independent
work and ask only for missing authority or information that actually prevents
further progress. Stopping a scientific run does not delete caches or data.

After source changes, a dry run may invalidate affected scientific outputs.
Do not suppress rerun triggers or manufacture completion markers simply to
reuse them. Full packaging rechecks large-file checksums; ordinary status
checks use the lighter recorded metadata where documented.

For completed stage outputs up to 8 MiB, checkpoint recovery freshly compares
size and SHA-256. A downstream rule can reproduce identical bytes with a new
mtime; that alone is not new scientific evidence and must not restart the
upstream review chain. Saved parent records remain unchanged. Large outputs
retain strict metadata checks and full final-delivery hashing. Changed input
fingerprints still invalidate their stages. A disclosure-only resume should
reuse the completed analysis rather than repeat phasing.

The existing BWA index has a dedicated original environment definition. Do not
replace `workflow/envs/bwa_index.yaml` with the broader current read environment
merely to add parser or QC dependencies: this can trigger reindexing, and the
scheduler deletes declared outputs before rerunning a shell rule. The separate
`record_bwa_provenance` rule is read-only with respect to index files. A mismatch
in reference identity or BWA executables stops for investigation without
blessing compatibility or erasing the preserved sidecars.

Read reassessment can replace the working table after excluding or reordering
proposals. The unified read worker first archives its exact bytes under
`work/private/read_evidence/<sha256>.tsv`, then links the decision and earlier
decisions through immutable JSON archives. Preserve CRLF bytes: ordinary text
newline conversion changes the evidence checksum. The delivery gate checks
archive hashes, the declared exclusion/ranking policy, and current finalist
coverage; an unverifiable older decision is not silently overwritten.

The first live run predated that archive step. Its original table was recovered
from the unchanged CRAM using the original proposal intervals and phasing; the
recovered SHA-256 exactly matched the pre-existing decision receipt. That
controller has finished. Do not rerun the private recovery or change the original
decision to fit new measurements. Its receipt is
`work/private/runner/read_evidence_recovery_state.json`.

Pitch rendering and assembly share the current PDF's hash-scoped page directory.
Missing, stale or duplicate pages fail before video assembly. Check the actual
bundle's full decode and duration, not only the separate synthetic smoke test.
Re-verifying an unchanged local model preserves its installation identity after
the full checksum and GPU gates; timestamps alone must not create a new model.

The real bundle passed independent artifact checks at 01:03 UTC on 2026-09-06,
including full scientific hashes and strict decoding of the 138.129313-second
MP4. Its status remains `draft_missing_disclosure` until the hosted account plan
and data-sharing setting are confirmed in config/ai_usage.local.yaml. The formal
dataset citation also needs organiser confirmation. Preserve the checked draft
and its receipts; do not retry unchanged packaging or invent disclosure values.
Recheck the current audit and code-release receipts before treating this dated
snapshot as current acceptance.

## Verification and publication

```bash
# Synthetic tests only; these never establish real scientific completion.
TMPDIR="$PWD/work/private/tmp" .conda/launcher/bin/python -m pytest -q

# Audit eligible source files; print only pass/fail and safe counts.
PYTHONPATH=src .conda/launcher/bin/python -m mva_runner.publication
```

Publish coherent, audited code changes to `HLEOT/mva-hackathon-2026` as they
become ready. Preserve the original staged index and concurrent remote work;
never use an indiscriminate staging command or force-push. Verify each commit's
remote files and hashes. A docs-only or partial code commit is not a completed
release. The full acceptance checklist remains in [the plan](00_execution_plan.md).
