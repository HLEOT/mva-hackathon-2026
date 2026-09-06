# MVA project instructions

Read `docs/00_execution_plan.md` completely before implementation. Keep its
progress, decisions, verification results, and next action current.

- Complete both tracks and the real analysis; synthetic tests alone are not completion.
- Preserve existing staged work, source data, verified results and provenance.
- Codex directs analysis here; scientific programs run on this PC. Do not
  install a separate LLM, inference server, hosted API client or nested agent.
- Use at most 112 CPUs and 400 GiB RAM. The additional disk allowance is
  400,000,000,000 bytes beyond the recorded baseline, explicitly approved on
  2026-09-05. Ask before exceeding it; do not reset the baseline.
- Keep task downloads, caches, environments, and scratch files in this project.
- Until the hackathon's provider terms are confirmed for this Codex account,
  never expose private phenotype, genotype, variant or review content here.
  Codex can inspect code, public resources, synthetic fixtures, technical counts
  and sanitised errors now. Running tools on the PC does not make hosted Codex
  inference local. Do not infer account terms, settings or consent from login.
- Use synthetic fixtures to diagnose scientific parser and review errors.
- Local workers must stop at an explicit Codex review checkpoint when review
  is needed. They must not transmit evidence or silently substitute a model.
- Be space-aware: autonomously remove verified disposable task files, redundant
  installation archives and caches when idle. Validate installed replacements
  and retain download URLs, hashes and a cleanup receipt before deletion.
  Never use broad recursive cleanup, follow symlinks, remove active-job scratch,
  delete unique evidence, reset the storage baseline or retain duplicate large
  backups merely to call deletion recoverable. Do not recompress indexed data.
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
