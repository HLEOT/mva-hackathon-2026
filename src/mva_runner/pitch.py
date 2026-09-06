"""Locally render, narrate and validate a timed research pitch.

Slide text is derived from accepted local results. Synthetic narration is
disclosed. No voice is cloned and no audio or patient content is uploaded.
"""
from __future__ import annotations

import array
import json
import math
import subprocess
import textwrap
import wave
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen.canvas import Canvas

from mva_track1.common import PROJECT_ROOT, Track1Error, atomic_write_json, atomic_write_text
from mva_track1.report import ACKNOWLEDGEMENT
from .render import inspect_pdf, register_fonts, rendered_pdf_pages
from .speech import BINARY, prepare as prepare_speech

FFMPEG = PROJECT_ROOT / '.conda/delivery/bin/ffmpeg'
FFPROBE = PROJECT_ROOT / '.conda/delivery/bin/ffprobe'


def _words(text: str, maximum: int) -> str:
    tokens = text.split()
    return ' '.join(tokens[:maximum]) + ('…' if len(tokens) > maximum else '')


def make_slides(finalists: list[dict], hypotheses: dict, evidence_count: int, username: str) -> list[dict]:
    lead = finalists[0]
    retained = hypotheses['hypotheses']
    names = ', '.join(h['drug'] for h in retained) if retained else 'No supported drug hypothesis'
    main = retained[0] if retained else None
    return [
        {'title': 'From variants to testable hypotheses', 'eyebrow': 'MVA HACKATHON 2026',
         'points': [username + ' | Both research tracks', 'Private analysis stays on device', 'Evidence and uncertainty travel together'],
         'narration': 'This project connects variant prioritisation with cautious drug repurposing research. Both tracks run locally with checkpoints and evidence checks. The results are research hypotheses, not a diagnosis or a recommendation to give any medication. This pitch uses locally generated synthetic narration.'},
        {'title': 'Track 1: preserve the evidence chain', 'eyebrow': 'GENOME → PHENOTYPE → READS',
         'points': ['GRCh38 reference checks, normalisation and offline annotation', 'Exomiser plus genome-wide and historical comparisons', 'Both alleles evaluated; read support and phase kept explicit'],
         'narration': 'Track one checks the supplied data against the reference, normalises variants, and annotates them offline. Exomiser combines phenotype and variant evidence. The ranking considers both alleles and retains a genome-wide comparison. Raw reads test the selected hypotheses. Unresolved phase is not described as confirmed compound heterozygosity.'},
        {'title': 'A ranked hypothesis is not a diagnosis', 'eyebrow': 'TRACK 1 RESULT',
         'points': [f"Leading research gene: {lead['gene']}", f"Read evidence: {lead['pair_support']}", f"Phase: {lead['phase_status']}"],
         'narration': f"The leading research hypothesis involves {lead['gene']}. Measured read support is {lead['pair_support']}, and phase is {lead['phase_status'].replace('_',' ')}. This evidence does not establish clinical causality. Orthogonal confirmation, family studies where appropriate, and functional experiments remain important next steps."},
        {'title': 'Track 2: mechanism before medication', 'eyebrow': f'PUBLIC CORPUS | {evidence_count} LITERATURE RECORDS',
         'points': ['ChEMBL mechanisms and Reactome biology', 'PubMed evidence plus FDA approval and safety records', 'Unsupported mechanism or source claim → rejection'],
         'narration': 'Track two joins the private hypotheses to a public evidence collection. It combines drug mechanisms, checkpoint biology, primary literature, and regulatory records. Approval for another indication is not approval for mosaic variegated aneuploidy. A plausible network connection alone cannot establish that a drug repairs the biological defect.'},
        {'title': _words(names, 12), 'eyebrow': 'EXPERIMENTAL PRIORITIES',
         'points': [_words(main['conditional_mechanism'], 24), _words(main['experiment'], 24), 'Safety and mechanism remain explicit uncertainties'] if main else
                   ['No candidate passed every declared evidence gate', 'Resolve variant mechanism before stronger drug claims', 'Negative screening results are retained, not hidden'],
         'narration': ('The retained leads are conditional hypotheses for laboratory experiments. ' + _words(main['conditional_mechanism'], 23) + '. The decisive experiment is: ' + _words(main['experiment'], 25) + '.') if main else
                      'No drug hypothesis passed every declared gate for a variant-mechanism-linked experimental rationale. That is a meaningful boundary on the evidence, not proof that no treatment could exist. The next priority is to resolve the variant mechanism and use appropriate cellular models before making stronger repurposing claims.'},
        {'title': 'Reproducible work; responsible next steps', 'eyebrow': 'ACKNOWLEDGEMENT & HANDOFF',
         'points': ['Audited code release; private provenance and reports', 'Independent validation before any clinical interpretation', 'With gratitude to the child, family and organisers'],
         'narration': ACKNOWLEDGEMENT},
    ]


def render_slides(slides: list[dict], output: Path) -> dict:
    font = register_fonts()
    canvas = Canvas(str(output), pagesize=(1280, 720))
    canvas.setTitle('MVA Hackathon 2026 research pitch')

    def lines(text, size, width):
        result, line = [], ''
        for word in text.split():
            candidate = (line + ' ' + word).strip()
            if line and pdfmetrics.stringWidth(candidate, font, size) > width:
                result.append(line)
                line = word
            else:
                line = candidate
        return result + ([line] if line else [])

    for index, slide in enumerate(slides, 1):
        canvas.setFillColor(colors.HexColor('#0c2533'))
        canvas.rect(0, 0, 1280, 720, fill=1, stroke=0)
        canvas.setFillColor(colors.HexColor('#4cdbbd'))
        canvas.rect(64, 620, 60, 6, fill=1, stroke=0)
        canvas.setFont(font, 17)
        canvas.drawString(64, 650, slide['eyebrow'])
        canvas.setFillColor(colors.white)
        title_lines = lines(slide['title'], 42, 1140)
        if len(title_lines) > 2:
            raise Track1Error('Pitch title exceeds the designed slide area')
        for number, line in enumerate(title_lines):
            canvas.setFont(font, 42)
            canvas.drawString(64, 560 - number * 51, line)
        y = 402
        for point in slide['points']:
            wrapped = lines(point, 25, 1075)
            canvas.setFillColor(colors.HexColor('#4cdbbd'))
            canvas.circle(72, y + 8, 5, fill=1, stroke=0)
            canvas.setFillColor(colors.HexColor('#e5edf0'))
            canvas.setFont(font, 25)
            for line in wrapped:
                canvas.drawString(99, y, line)
                y -= 35
            y -= 29
        if y < 90:
            raise Track1Error('Pitch text exceeds the designed slide area')
        canvas.setFont(font, 14)
        canvas.setFillColor(colors.HexColor('#a9bec7'))
        canvas.drawString(64, 34, 'Research only • No clinical recommendation • Local synthetic narration')
        canvas.drawRightString(1216, 34, f'{index:02d} / {len(slides):02d}')
        canvas.showPage()
    canvas.save()
    return inspect_pdf(output, len(slides))


def build_pitch(directory: Path, slides: list[dict], max_seconds: float = 180) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    prepare_speech()
    if not FFMPEG.exists() or not FFPROBE.exists():
        raise Track1Error('Project-local FFmpeg delivery environment is not installed')
    pdf = directory / 'pitch_slides.pdf'
    rendering = render_slides(slides, pdf)
    # The renderer retains old previews in separate hash-named directories.
    # Consume only this PDF's verified page set, with one frame per narration.
    frames = rendered_pdf_pages(pdf, len(slides))
    durations = []
    speed = 155
    for attempt in range(3):
        durations.clear()
        for index, slide in enumerate(slides, 1):
            script = directory / f'slide_{index:02d}.txt'
            audio = directory / f'slide_{index:02d}.wav'
            atomic_write_text(script, slide['narration'] + '\n')
            subprocess.run([str(BINARY), '-v', 'en-gb', '-s', str(speed), '-f', str(script), '-w', str(audio)],
                           check=True, capture_output=True)
            with wave.open(str(audio)) as stream:
                duration = stream.getnframes() / stream.getframerate()
                samples = array.array('h', stream.readframes(stream.getnframes()))
                if not samples or max(abs(value) for value in samples) < 100:
                    raise Track1Error('Narration audio is silent or invalid')
            durations.append(duration + 0.3)
        total = sum(durations)
        if total <= min(178, max_seconds - 1):
            break
        speed = math.ceil(speed * total / (max_seconds - 4))
        if speed > 195:
            raise Track1Error('Pitch is too long for clear narration; shorten the script')
    if sum(durations) > max_seconds - 1:
        raise Track1Error('Narration does not fit the permitted pitch duration')
    segments = []
    timeline, elapsed = [], 0.0
    for index, (slide, frame, duration) in enumerate(zip(slides, frames, durations, strict=True), 1):
        segment = directory / f'segment_{index:02d}.mp4'
        subprocess.run([str(FFMPEG), '-nostdin', '-y', '-v', 'error', '-loop', '1', '-i', str(frame),
            '-i', str(directory / f'slide_{index:02d}.wav'), '-af', 'apad', '-t', f'{duration:.3f}',
            '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2',
            '-c:v', 'libx264', '-preset', 'fast', '-tune', 'stillimage', '-threads', '8', '-r', '24',
            '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k', str(segment)], check=True, capture_output=True)
        segments.append(segment)
        timeline.append({'slide': index, 'start_seconds': round(elapsed, 3), 'duration_seconds': round(duration, 3),
                         'title': slide['title'], 'narration': slide['narration']})
        elapsed += duration
    listing = directory / 'segments.txt'
    atomic_write_text(listing, ''.join("file '" + str(path.resolve()).replace("'", "'\\''") + "'\n" for path in segments))
    video = directory / 'pitch.mp4'
    subprocess.run([str(FFMPEG), '-nostdin', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listing),
                    '-c', 'copy', '-movflags', '+faststart', str(video)], check=True, capture_output=True)
    check = json.loads(subprocess.run([str(FFPROBE), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(video)],
                                     capture_output=True, text=True, check=True).stdout)
    seconds = float(check['format']['duration'])
    kinds = {s['codec_type'] for s in check['streams']}
    if not 1 <= seconds <= max_seconds or not {'audio', 'video'} <= kinds:
        raise Track1Error('Pitch failed its final duration/audio/video gate')
    subprocess.run([str(FFMPEG), '-nostdin', '-v', 'error', '-i', str(video), '-f', 'null', '-'],
                   check=True, capture_output=True)
    atomic_write_json(directory / 'timeline.json', {'speech_words_per_minute': speed, 'slides': timeline, 'duration_seconds': seconds})
    atomic_write_text(directory / 'pitch_script.md', '# Timed pitch script\n\nLocal synthetic narration. Research only.\n\n' +
        '\n\n'.join(f"## {s['start_seconds']:.1f}s — {s['title']}\n\n{s['narration']}" for s in timeline))
    return {'duration_seconds': seconds, 'full_decode_passed': True, 'narration': 'local_espeak_ng_synthetic', 'slides': rendering}
