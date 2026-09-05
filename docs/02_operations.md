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
- The additional allowance is 250,000,000,000 decimal bytes, not free space on
  the host and not 250 GiB. The stored baseline must never be increased to
  conceal task growth.
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
