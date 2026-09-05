# MVA project instructions

Read `docs/00_execution_plan.md` completely before implementation. Keep its
progress, decisions, verification results, and next action current.

- Complete both tracks and the real analysis; synthetic tests alone are not completion.
- Preserve existing staged work and validated resources.
- Use at most 112 CPUs and 400 GiB RAM. The additional disk allowance is
  400,000,000,000 bytes beyond the recorded baseline, explicitly approved on
  2026-09-05. Ask before exceeding it; do not reset the baseline.
- Keep task downloads, caches, environments, and scratch files in this project.
- Never print private phenotype, genotype, variant, or local model content to
  a hosted agent. Inspect it with local code and expose only technical status,
  artifact counts, and sanitised errors to the coding conversation.
- Use synthetic fixtures to diagnose scientific parser and inference errors.
- Bind authenticated inference to loopback. Never use a hosted fallback for
  patient content.
- Code-only publication to HLEOT/mva-hackathon-2026 is authorised. Audit an
  explicit allowlist; exclude data, private outputs, secrets, caches, weights,
  and environment files.
- Comment biological assumptions, coordinate conventions, units, and recovery
  behaviour for a bioinformatician.
- Follow long jobs by their live process identity. An observation timeout is
  not evidence that a job stopped.
- Preserve uncertainty. Never invent human review, phase, approval, evidence,
  or successful checks.

Keep synthetic test scratch inside the project too. Run tests with:

```bash
mkdir -p -m 700 work/private/tmp
TMPDIR="$PWD/work/private/tmp" .conda/launcher/bin/python -m pytest -q
```
