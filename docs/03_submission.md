# Private submission materials and final handoff

<!-- This document describes the contract, not a claim that a bundle is complete. -->

The final bundle is built locally under `submissions/`. Keep it out of the public
repository. Current scientific progress and unresolved prerequisites are in
[the execution plan](00_execution_plan.md).

## Expected deliverables

`<hf-user>` is the verified submission identity, not a placeholder to leave in
the real files.

| Local artifact | Acceptance gate |
|---|---|
| `<hf-user>_track1_submission.csv` | Current official schema, at most ten rows, GRCh38 coordinates, unique ranks |
| `<hf-user>_track1_report.md` and `.pdf` | Evidence, methods, limitations, references, acknowledgement and AI disclosure |
| `<hf-user>_track2_report.md` and `.pdf` | Mechanism-linked hypotheses or an explicit supported negative result |
| `<hf-user>_track1_methods.xlsx` and `<hf-user>_track2_methods.xlsx` | Official template topology preserved and every required answer complete |
| `pitch/pitch_slides.pdf` | Rendered, legible slides without clipped content |
| `pitch/pitch_script.md` and `pitch/timeline.json` | Timed script with explicit synthetic narration |
| `pitch/pitch.mp4` | Audio/video streams, full decode, duration at most 180 seconds |
| `delivery_manifest.json` | Artifact sizes/checksums, provenance and actual validation outcomes |
| `HANDOFF.md` | Remaining user actions stated truthfully |

Scientific provenance is retained in `results/private/final_run_manifest.json`;
Track 2 evidence and decisions are under `results/private/track2/`. Resolve
every required artifact against actual files, not just this inventory.

## Required disclosure and current-source checks

Record the actual hosted coding account plan and data-sharing/model-training
setting in ignored `config/ai_usage.local.yaml`, using fields `hosted_plan` and
`hosted_data_setting`. The model cannot infer those account settings. Missing
disclosure leaves the bundle a draft and prevents final acceptance. Distinguish
hosted code assistance from local Qwen analysis of private data.

Use the official methods workbook and current challenge instructions, retaining
retrieval dates, revisions and hashes. Packaging compares cached bytes with the
upstream Git/LFS digests and checks whether selected rules or templates changed
at the current Space head; changes require review rather than silent repinning.
Recheck mutable rules and the authoritative
Synapse dataset citation before final publication/submission. Do not invent a
DOI, account setting, approval, human reviewer or completed check.

Reports must include the canonical code repository URL and the required
acknowledgement. The workflow's local geometry/raster tests and full video decode
are acceptance evidence; file existence alone is insufficient. Only synthetic
visual fixtures may be shown to a hosted coding agent.

## Completion versus external handoff

Local completion requires both real analyses, validated materials and a verified
public code release reproducible on synthetic fixtures from a clean environment.
Packaging verifies the live public GitHub tree against the current privacy-audited
paths, bytes and executable modes, then records the exact commit. This check does
not substitute for the separate clean-environment test. FDA identity checks retain
single-ingredient product and historical original-approval records, with explicit
source-linked salt mappings; neither labels alone nor combination products prove
single-agent approval, and approval history is not current availability or MVA efficacy.
An automated review does not establish clinical causality or treatment efficacy.
An unresolved phase or mechanism must remain explicitly unresolved.

The user retains these external actions:

- Review the private research outputs and unresolved scientific limitations.
- Host the pitch on an allowed video service and retain its URL.
- Submit through the official challenge interface under the verified identity.
- Recheck applicable deadlines, quotas and data-lifecycle obligations.
- Perform required post-challenge deletion and send any required confirmation.

No challenge submission, video hosting, deletion or email is performed merely
by building the bundle. Never mark these actions complete without evidence.

Authoritative requirements:
[challenge application](https://sagebio-rare-disease-real-kid-mva-hackathon-2026.hf.space/),
[rules source](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/blob/main/tabs/rules.py),
[official templates](https://huggingface.co/spaces/SageBio/rare-disease-real-kid-mva-hackathon-2026/tree/main/static/templates).
