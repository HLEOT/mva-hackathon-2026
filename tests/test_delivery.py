from pathlib import Path

from mva_runner.delivery import methods_answers
from mva_runner.pitch import make_slides
from mva_runner.render import markdown_to_pdf, inspect_pdf


def test_methods_have_every_official_answer_and_bounded_abstracts():
    answers = methods_answers('synthetic', 'Synthetic disclosure', 'Synthetic runtime', {'conclusion': 'No supported hypothesis.'})
    assert set(answers['Track 1 methods']) == set(range(7, 20))
    assert set(answers['Track 2 methods']) == set(range(7, 18))
    assert len(answers['Track 1 methods'][19].split()) <= 500
    assert len(answers['Track 2 methods'][17].split()) <= 500


def test_negative_track2_result_is_not_presented_as_a_drug_recommendation():
    slides = make_slides([{'gene': 'SYNTH', 'pair_support': 'ambiguous', 'phase_status': 'unresolved'}],
                         {'hypotheses': []}, 10, 'synthetic')
    assert len(slides) == 6
    assert 'No supported drug hypothesis' in slides[4]['title']
    assert len(' '.join(s['narration'] for s in slides).split()) < 450


def test_rendered_pdf_has_text_without_page_clipping(tmp_path):
    source = tmp_path / 'synthetic.md'
    source.write_text('# Synthetic evidence report\n\n## Research only\n\n'
                      'Unknown mechanism & unresolved phase are not confirmation.\n\n'
                      '- The next step is an experiment, not clinical administration.\n')
    output = source.with_suffix('.pdf')
    markdown_to_pdf(source, output)
    check = inspect_pdf(output)
    assert check['clipped_words'] == 0 and check['raster_pages_checked'] >= 1
