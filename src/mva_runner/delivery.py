"""Build the private, validated two-track submission bundle and handoff record."""
from __future__ import annotations

import csv
from datetime import datetime, timezone

from mva_track1.cli import _assert_package_readiness, _hf_username
from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, atomic_write_text, load_jsonish, sha256_file, utc_now
from mva_track1.report import ACKNOWLEDGEMENT, generate_markdown
from mva_track1.submission import _candidate_rows, build_submission, reviewed_finalists, validate_submission_file
from mva_track2.analysis import evidence_index, validate_hypothesis
from .official import ROOT as OFFICIAL, prepare as prepare_official
from .pitch import build_pitch, make_slides
from .render import inspect_pdf, markdown_to_pdf
from .storage import EXECUTION, require_space, snapshot
from .supervisor import read_state
from .workbooks import write_methods

OUTPUT = PROJECT_ROOT / 'submissions'
TRACK1 = PROJECT_ROOT / 'results/private'
DATASET_CITATION = ('Sage Bionetworks and MVA Society (2026). Rare Disease, Real Kid: The 2026 MVA Hackathon. '
    '[Synapse:syn76251147](https://www.synapse.org/Synapse:syn76251147/wiki/642892). '
    'Organiser-provided gated dataset; exact Hugging Face revision and file checksums are in the private provenance manifest. '
    'The inspected Synapse landing page did not display a separate DOI or formal dataset citation; recheck before publication.')


def ai_disclosure() -> tuple[str, list[str]]:
    path = PROJECT_ROOT / 'config/ai_usage.local.yaml'
    data = load_jsonish(path) if path.exists() else {}
    missing = [key for key in ['hosted_plan', 'hosted_data_setting'] if not str(data.get(key, '')).strip()]
    text = ('OpenAI Codex was used for public code implementation and synthetic tests. '
            f"Account plan/tier: {data.get('hosted_plan', 'NOT YET PROVIDED')}. "
            f"Account data-handling setting: {data.get('hosted_data_setting', 'NOT YET VERIFIED')}. "
            'This workflow did not send patient phenotype, genotype, or private interpretation prompts to hosted models. '
            'Private interpretation used Qwen3-30B-A3B Q4_K_M through a pinned local llama.cpp Vulkan runtime, '
            'with authenticated loopback requests, no fine-tuning, and owner-readable local prompt/response logs. '
            'These are automated research reviews, not human clinical curation.')
    return text, missing


def methods_answers(username: str, disclosure: str, runtime: str, track2: dict) -> dict:
    method1 = ('The supplied VCF is checksum-verified, mapped between length-checked GRCh38 chromosome aliases, '
        'REF-checked, normalised and split with bcftools. Offline VEP 116 and Exomiser 15.1.0/2602 exome-preset evidence '
        'are joined by allele and gene. Pinned HPO terms require exact local source anchors; conflicting or uncertain '
        'features are excluded from scoring. Candidate pairs use evidence for both alleles; same-locus and shared-block '
        'cis pairs are excluded. Genome-wide score ordering and the historical known-gene-prioritised comparator are retained. '
        'Selected hypotheses undergo local automated review, streamed duplicate-marked CRAM alignment, and measured read/phase validation.')
    method2 = ('Fixed public queries collect ChEMBL mechanisms, Reactome checkpoint biology, PubMed abstracts, and FDA '
        'approval/label records before joining private results locally. Structured local-model outputs cite supplied source '
        'IDs and exact quotes. Deterministic gates require supported variant mechanism, compound identity, existing regulatory '
        'approval, safety evidence and primary literature. A second local critique tests the conditional experimental rationale. '
        'Unknown mechanisms, invented evidence and unsupported candidates are rejected; no list is filled to an arbitrary target.')
    private = 'Only the authorised organiser-provided gated challenge genome and phenotype; no additional proprietary datasets.'
    public = 'GRCh38 reference, VEP merged cache 116, Exomiser 15.1.0/2602, HPO v2026-09-01, ChEMBL, Reactome 97, PubMed and official FDA records. Exact versions, retrieval dates and checksums are recorded locally.'
    return {
        'Track 1 methods': {
            7: username, 8: '1 (local approach identifier; not a claim about platform submission count)', 9: method1,
            10: disclosure, 11: 'Automated computational output with explicitly recorded local-model and deterministic reviews.',
            12: 'No downstream human clinical curation. Hosted coding review examined code, synthetic fixtures and sanitised operational summaries only.',
            13: 'Organiser-provided gated challenge data plus public reference resources; no additional proprietary resources.',
            14: public, 15: private, 16: 'Both same-gene heterozygous pairs and eligible single-variant hypotheses. Unresolved phase is not confirmation of compound heterozygosity.',
            17: 'Primary/secondary labels are explicit. Lower-ranked alternatives are not automatically called secondary findings; none is a clinical diagnosis.',
            18: runtime, 19: method1 + ' Strengths are source grounding, explicit uncertainty and resumability. Limitations include no independent whole-genome CNV/SV call, coding/splice-focused Exomiser prioritisation, incomplete non-coding interpretation and absent functional confirmation.'},
        'Track 2 methods': {
            7: username, 8: method2, 9: disclosure, 10: 'Automated public evidence collection followed by local model synthesis, deterministic checks and local critique.',
            11: 'No human expert clinical curation was performed. Automated critiques are not independent experimental validation.',
            12: 'Public drug/target and literature resources, joined locally to the authorised gated challenge analysis.', 13: public, 14: private,
            15: 'Only supplied predicted truncating or essential-splice consequences support a predicted loss-of-function category. Missense alone does not establish direction. Unknown mechanism remains unknown and fails the retention gate. No mechanism is claimed experimentally confirmed.',
            16: runtime, 17: method2 + ' ' + track2['conclusion'] + ' Strengths are traceable evidence and falsifiable experiments. Limitations include bounded searches, abstract-level literature access, incomplete mechanism knowledge, jurisdiction/formulation-specific approval and no demonstrated clinical efficacy.'}}


def track2_report(data: dict, corpus: dict, output, github: str, disclosure: str) -> None:
    lines = ['# Track 2 Drug-Repurposing Research Report', '', f'Generated: {utc_now()}', '',
        '## Outcome', '', data['conclusion'], '',
        'This report is not medical advice, a diagnosis, or a recommendation to administer any drug.', '',
        '## Method and scientific rigor', '',
        methods_answers('unused', disclosure, 'unused', data)['Track 2 methods'][8], '',
        f'Code repository: [{github}]({github}). Publication verification is recorded in the handoff manifest.', '',
        '## Variant mechanism and experimental hypotheses', '']
    if not data['hypotheses']:
        lines.extend(['No sufficiently supported candidate was retained. This does not prove that no treatment could exist. '
                      'Functional resolution of the leading variant mechanism is the next prerequisite for stronger repurposing claims.', ''])
    for index, item in enumerate(data['hypotheses'], 1):
        sources = evidence_index(corpus, item['drug'])
        lines.extend([f"### {index}. {item['drug']}", '', item['conditional_mechanism'], '',
                      'Intervention direction: ' + item['intervention_direction'], '', item['rationale'], ''])
        for claim in item['supporting_evidence']:
            source = sources[claim['source_id']]
            lines.extend([claim['interpretation'] + f" Evidence category: {claim['evidence_type']}. "
                          f"[{claim['source_id']}]({source['url']}).", ''])
        lines.extend(['Opposing evidence: ' + item['opposing_evidence'], '',
                      'Safety concerns: ' + item['safety_concerns'], '', 'Decisive experiment: ' + item['experiment'], ''])
        for approval in item['approval']:
            lines.extend([f"Existing approval, not for MVA: {approval['jurisdiction']}; "
                          f"[{approval['application_number']}]({approval['url']}).", ''])
        lines.extend(['- ' + limit for limit in item['limitations']])
        lines.append('')
    lines.extend(['## Rejected hypotheses and limitations', ''])
    for item in data['decisions']:
        if not item['accepted_as_experimental_hypothesis']:
            lines.extend([f"### {item['drug']}", '', item['rationale'], '',
                          'Retention failures: ' + ', '.join(item['validation_failures']) + '.', ''])
    lines.extend(['- ' + limit for limit in data['coverage_limitations']])
    lines.extend(['', '## Potential impact, innovation and scalability', '',
        'The intended impact is a prioritised, testable research programme, not a treatment claim. Mechanism and safety gates '
        'make unsupported proposals visible. Fixed public knowledge collection and private local joins permit reuse across cases '
        'without placing patient-derived queries in external services. Checkpointed execution, bounded resources and retained negative '
        'results make the approach reproducible; independent functional and clinical validation remain essential.', '',
        '## Actual AI use and data handling', '', disclosure, '', '## Dataset citation', '', DATASET_CITATION, '',
        '## Required acknowledgement', '', ACKNOWLEDGEMENT, ''])
    atomic_write_text(output, '\n'.join(lines))


def package() -> None:
    require_space(1_000_000_000)
    cfg = load_jsonish(EXECUTION)
    username = cfg['delivery']['hf_username']
    github = 'https://github.com/' + cfg['delivery']['github_repository']
    if _hf_username() != username:
        raise Track1Error('Submission Hugging Face identity could not be reverified')
    identity = PROJECT_ROOT / 'config/submission.local.json'
    if not identity.exists():
        atomic_write_json(identity, {'hf_username': username, 'github_url': github})
    _assert_package_readiness(verify_large_hashes=True)
    prepare_official()
    disclosure, missing = ai_disclosure()
    OUTPUT.mkdir(exist_ok=True)
    candidates_path = TRACK1 / 'candidates_ranked.tsv'
    finalists_path = PROJECT_ROOT / 'config/finalists.local.tsv'
    validation_path = TRACK1 / 'read_validation.tsv'
    candidates = _candidate_rows(candidates_path)
    finalists = reviewed_finalists(finalists_path, candidates_path)
    with validation_path.open() as source:
        measured = {r['candidate_id']: r for r in csv.DictReader(source, delimiter='\t')}
    data = load_jsonish(TRACK1 / 'track2/hypotheses.json')
    corpus = load_jsonish(PROJECT_ROOT / 'resources/public/evidence/corpus.json')
    for hypothesis in data['hypotheses']:
        failures = validate_hypothesis(hypothesis, candidates, corpus['drugs'][hypothesis['drug']], evidence_index(corpus, hypothesis['drug']))
        if failures:
            raise Track1Error('A retained Track 2 hypothesis failed delivery-time evidence validation')
    submission = OUTPUT / f'{username}_track1_submission.csv'
    build_submission(candidates_path, finalists_path, submission, validation_path)
    validate_submission_file(submission)
    report1, report2 = [OUTPUT / f'{username}_track{track}_report.md' for track in [1, 2]]
    generate_markdown(candidates_path, finalists_path, validation_path, TRACK1 / 'final_run_manifest.json', report1, github)
    atomic_write_text(report1, report1.read_text() + '\n## Evidence-policy changes\n\n'
        'The current ranking uses the weaker allele for effect, technical and Exomiser evidence in a pair. '
        'The historical arithmetic and known-gene-first ordering are retained in the baseline comparator. '
        'Same-locus and input-cis pairs cannot enter the current shortlist. Reads may remove contradicted hypotheses; '
        'the immutable pre-read proposal and reassessment record retain that decision trail.\n\n'
        '## Actual AI use and data handling\n\n' + disclosure + '\n\n## Dataset citation\n\n' + DATASET_CITATION + '\n')
    track2_report(data, corpus, report2, github, disclosure)
    checks, artifacts = {}, [submission, report1, report2]
    for report in [report1, report2]:
        pdf = report.with_suffix('.pdf')
        markdown_to_pdf(report, pdf)
        checks[pdf.name] = inspect_pdf(pdf)
        artifacts.append(pdf)
    state = read_state()
    starts = [r['started_at'] for r in state['stages'].values() if r.get('started_at')]
    elapsed = (datetime.now(timezone.utc) - min(datetime.fromisoformat(t) for t in starts)).total_seconds() if starts else 0
    runtime = (f'Supervised elapsed time to packaging: {elapsed / 3600:.2f} hours, including setup and waits. '
               'No paid compute or hosted inference service was purchased by the workflow. Existing host, electricity '
               'and coding-subscription costs were not metered. CPU/RAM/storage limits and solved environments are in provenance.')
    answers = methods_answers(username, disclosure, runtime, data)
    for track in [1, 2]:
        path = OUTPUT / f'{username}_track{track}_methods.xlsx'
        checks[path.name] = write_methods(OFFICIAL / 'static/templates/methods_description_form.xlsx', path, answers)
        artifacts.append(path)
    pitch_dir = OUTPUT / 'pitch'
    leads = [{**candidates[r['candidate_id']], **measured[r['candidate_id']]} for r in finalists]
    slides = make_slides(leads, data, len(corpus['literature']), username)
    checks['pitch'] = build_pitch(pitch_dir, slides, cfg['delivery']['maximum_pitch_seconds'])
    artifacts += [pitch_dir / name for name in ['pitch.mp4', 'pitch_slides.pdf', 'pitch_script.md', 'timeline.json']]
    checklist = OUTPUT / 'HANDOFF.md'
    atomic_write_text(checklist, '# Submission handoff\n\n'
        '- [ ] Verify hosted AI plan and data-handling disclosure before submission.\n'
        '- [ ] Verify the audited public code release and repository URL.\n'
        '- [ ] Review the local research outputs; unresolved mechanism or phase is not confirmation.\n'
        '- [ ] Upload the pitch to YouTube or Vimeo and retain its URL.\n'
        '- [ ] Submit the username-labelled CSV/report and methods workbooks through the official challenge UI.\n'
        '- [ ] Recheck current rules, quotas, deadline and dataset citation before submission/publication.\n'
        '- [ ] Delete restricted source data and genotype-scale derivatives within the required post-close window '
        'and send the required deletion confirmation yourself. No deletion or email has been performed automatically.\n\n'
        'Competition submission and video hosting remain user handoff actions.\n')
    artifacts.append(checklist)
    manifest = {'created_at': utc_now(), 'status': 'draft_missing_disclosure' if missing else 'validated_local_bundle',
        'missing_disclosure_fields': missing, 'github_url': github, 'checks': checks, 'storage': snapshot(),
        'artifacts': {str(p.relative_to(PROJECT_ROOT)): {'size': p.stat().st_size, 'sha256': sha256_file(p)} for p in artifacts},
        'scientific_manifest_sha256': sha256_file(TRACK1 / 'final_run_manifest.json'),
        'track2_manifest_sha256': sha256_file(TRACK1 / 'track2/hypotheses.json'),
        'official_requirements_sha256': sha256_file(OFFICIAL / 'manifest.json'),
        'external_handoff': ['challenge_submission', 'video_hosting'], 'publication_verified': False}
    atomic_write_json(OUTPUT / 'delivery_manifest.json', manifest)
    if missing:
        raise Track1Error('Local draft bundle built; hosted AI plan/data setting still requires user confirmation')
