"""Deterministic document rendering with local, non-disclosing acceptance checks."""
from __future__ import annotations

import html
import re
import subprocess
from pathlib import Path
from xml.etree import ElementTree

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from mva_track1.common import Track1Error, sha256_file


def register_fonts() -> str:
    font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if font.exists():
        if 'MVA' not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont('MVA', str(font)))
        return 'MVA'
    return 'Helvetica'


def inline(text: str) -> str:
    """Escape patient/model text before adding a small safe Markdown subset."""
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https://[^\s)]+)\)', r'<link href="\2" color="#146b75">\1</link>', text)
    return text.replace('`', '')


def markdown_to_pdf(markdown: Path, pdf: Path) -> None:
    font = register_fonts()
    styles = getSampleStyleSheet()
    for name in ['Title', 'Heading1', 'Heading2', 'Heading3', 'BodyText']:
        styles[name].fontName = font
        styles[name].textColor = colors.HexColor('#193443')
    styles['BodyText'].fontSize, styles['BodyText'].leading = 9.5, 14
    styles['Title'].fontSize, styles['Title'].leading = 22, 28
    styles['Heading2'].spaceBefore, styles['Heading2'].spaceAfter = 12, 6
    story, paragraph = [], []

    def flush():
        if paragraph:
            story.append(Paragraph(inline(' '.join(paragraph)), styles['BodyText']))
            story.append(Spacer(1, 2 * mm))
            paragraph.clear()

    for raw in markdown.read_text().splitlines():
        line = raw.strip()
        if not line:
            flush()
        elif line.startswith('#'):
            flush()
            level = len(line) - len(line.lstrip('#'))
            style = 'Title' if level == 1 else 'Heading2' if level == 2 else 'Heading3'
            story.append(Paragraph(inline(line.lstrip('#').strip()), styles[style]))
        elif line.startswith('- '):
            flush()
            story.append(Paragraph(inline(line[2:]), styles['BodyText'], bulletText='•'))
        else:
            paragraph.append(line)
    flush()

    def footer(canvas, doc):
        canvas.setFont(font, 8)
        canvas.setFillColor(colors.HexColor('#526774'))
        canvas.drawString(18 * mm, 11 * mm, 'MVA Hackathon 2026 | Research only | Private submission bundle')
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, str(doc.page))
    pdf.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(pdf), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                      topMargin=17 * mm, bottomMargin=21 * mm).build(story, onFirstPage=footer, onLaterPages=footer)


def pdf_preview_directory(pdf: Path) -> Path:
    """Keep one canonical, content-addressed location for a PDF's raster pages."""
    return pdf.parent / (pdf.stem + '_render') / sha256_file(pdf)[:16]


def rendered_pdf_pages(pdf: Path, expected_pages: int) -> list[Path]:
    """Return exactly the current PDF's pages in numeric narration order.

    Never borrow pages from an older PDF or let zip silently omit slides when
    a render is missing. Padded and unpadded page numbers must not alias.
    """
    if expected_pages < 1:
        raise Track1Error('A rendered PDF must have at least one expected page')
    pages = {}
    for path in pdf_preview_directory(pdf).glob('page-*.png'):
        match = re.fullmatch(r'page-([0-9]+)\.png', path.name)
        if not match or path.is_symlink() or not path.is_file():
            raise Track1Error('Rendered PDF has an invalid raster page')
        number = int(match.group(1))
        if number in pages:
            raise Track1Error('Rendered PDF has duplicate raster page numbers')
        pages[number] = path
    if set(pages) != set(range(1, expected_pages + 1)):
        raise Track1Error('PDF raster inventory does not match the expected pages')
    return [pages[number] for number in range(1, expected_pages + 1)]


def inspect_pdf(pdf: Path, expected_pages: int | None = None) -> dict:
    """Inspect rendered text geometry locally; return no document text to callers.

    Bounding boxes detect clipping beyond page margins. Raster decoding catches
    corrupt pages; a pixel-variance check rejects blank renderings. Only safe
    counts and pass/fail metrics enter the delivery manifest.
    """
    result = subprocess.run(['pdftotext', '-bbox', str(pdf), '-'], text=True, capture_output=True, check=True)
    root = ElementTree.fromstring(result.stdout)
    pages = [node for node in root.iter() if node.tag.endswith('page')]
    if not pages or (expected_pages is not None and len(pages) != expected_pages):
        raise Track1Error('Rendered PDF has an unexpected page count')
    words, clipped = 0, 0
    for page in pages:
        width, height = float(page.attrib['width']), float(page.attrib['height'])
        for word in page.iter():
            if not word.tag.endswith('word'):
                continue
            words += 1
            if (float(word.attrib['xMin']) < 1 or float(word.attrib['yMin']) < 1 or
                float(word.attrib['xMax']) > width - 1 or float(word.attrib['yMax']) > height - 1):
                clipped += 1
    if not words or clipped:
        raise Track1Error('Rendered PDF contains missing or clipped text')
    from PIL import Image, ImageStat
    # Content-addressed previews cannot inherit stale pages when a revised
    # report is shorter. Retain prior inspection evidence instead of deleting it.
    preview = pdf_preview_directory(pdf)
    preview.mkdir(parents=True, exist_ok=True)
    subprocess.run(['pdftoppm', '-scale-to', '1280', '-png', str(pdf), str(preview / 'page')],
                   check=True, capture_output=True)
    images = rendered_pdf_pages(pdf, len(pages))
    for image in images:
        with Image.open(image) as opened:
            if ImageStat.Stat(opened.convert('L')).var[0] < 5:
                raise Track1Error('PDF raster inspection found an effectively blank page')
    return {'pages': len(pages), 'word_count': words, 'clipped_words': clipped,
            'raster_pages_checked': len(images), 'inspection_mode': 'automated_local_geometry_and_raster'}
