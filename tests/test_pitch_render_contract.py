"""Synthetic renderer-to-pitch integration; no patient text or audio is used."""
import json
import struct
import subprocess
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from mva_runner import pitch
from mva_runner.render import pdf_preview_directory, rendered_pdf_pages
from mva_track1.common import Track1Error


def test_raster_inventory_is_numeric_and_hash_scoped(tmp_path):
    pdf = tmp_path / 'synthetic.pdf'
    pdf.write_bytes(b'synthetic PDF identity for a path-contract test')
    preview = pdf_preview_directory(pdf)
    preview.mkdir(parents=True)
    for number in range(1, 11):
        (preview / f'page-{number}.png').write_bytes(b'synthetic path fixture')
    # An earlier flat-directory layout must never supply a current frame.
    (preview.parent / 'page-999.png').write_bytes(b'stale path fixture')
    assert [p.name for p in rendered_pdf_pages(pdf, 10)] == [f'page-{n}.png' for n in range(1, 11)]


def test_missing_current_frames_fail_before_encoding(tmp_path):
    pdf = tmp_path / 'synthetic.pdf'
    pdf.write_bytes(b'synthetic PDF identity')
    old = tmp_path / 'synthetic_render'
    old.mkdir()
    (old / 'page-1.png').write_bytes(b'old flat-directory frame')
    with pytest.raises(Track1Error, match='inventory'):
        rendered_pdf_pages(pdf, 1)


def test_duplicate_numeric_page_aliases_are_rejected(tmp_path):
    pdf = tmp_path / 'synthetic.pdf'
    pdf.write_bytes(b'synthetic PDF identity')
    preview = pdf_preview_directory(pdf)
    preview.mkdir(parents=True)
    for name in ['page-1.png', 'page-01.png']:
        (preview / name).write_bytes(b'synthetic path fixture')
    with pytest.raises(Track1Error, match='duplicate'):
        rendered_pdf_pages(pdf, 1)


def test_pitch_consumes_the_actual_renderer_page_directory(tmp_path, monkeypatch):
    # Use the real PDF/Poppler renderer. Only speech and video encoding are
    # mocked here; a separate local smoke test exercises those executables.
    ffmpeg, ffprobe, speech = [tmp_path / name for name in ['fake-ffmpeg', 'fake-ffprobe', 'fake-speech']]
    ffmpeg.touch()
    ffprobe.touch()
    monkeypatch.setattr(pitch, 'FFMPEG', ffmpeg)
    monkeypatch.setattr(pitch, 'FFPROBE', ffprobe)
    monkeypatch.setattr(pitch, 'BINARY', speech)
    monkeypatch.setattr(pitch, 'prepare_speech', lambda: None)
    actual_run = subprocess.run
    frames = []

    def run(args, **kwargs):
        executable = Path(args[0])
        if executable == speech:
            output = Path(args[args.index('-w') + 1])
            with wave.open(str(output), 'wb') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(8000)
                stream.writeframes(struct.pack('<h', 300) * 8000)
            return SimpleNamespace(returncode=0)
        if executable == ffmpeg:
            if '-loop' in args:
                frame = Path(args[args.index('-i') + 1])
                assert frame.is_file()
                frames.append(frame)
            return SimpleNamespace(returncode=0)
        if executable == ffprobe:
            return SimpleNamespace(returncode=0, stdout=json.dumps({
                'format': {'duration': '2.6'}, 'streams': [{'codec_type': 'audio'}, {'codec_type': 'video'}]}))
        return actual_run(args, **kwargs)

    monkeypatch.setattr(pitch.subprocess, 'run', run)
    slides = [{'title': f'Synthetic slide {n}', 'eyebrow': 'TEST ONLY',
               'points': ['Invented evidence for rendering tests'], 'narration': 'Synthetic narration.'}
              for n in [1, 2]]
    directory = tmp_path / 'pitch'
    result = pitch.build_pitch(directory, slides, max_seconds=10)
    expected = pdf_preview_directory(directory / 'pitch_slides.pdf')
    assert len(frames) == 2 and all(path.parent == expected for path in frames)
    assert result['slides']['raster_pages_checked'] == 2
    assert result['duration_seconds'] == 2.6
