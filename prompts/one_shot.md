# One-shot model handoff

<!-- Keep this prompt aligned with docs/00_execution_plan.md. The plan owns
     detailed requirements and progress; this file is the copy-and-paste entry. -->

Copy the following block into a coding model with access to this checkout.
The complete plan is [docs/00_execution_plan.md](../docs/00_execution_plan.md).
Use the same prompt to start or resume; it does not promise unlimited model
runtime or bypass service limits.

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
services. Enforce a combined limit of 400 GB additional disk usage beyond the
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
