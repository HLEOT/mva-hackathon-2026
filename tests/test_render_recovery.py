"""Render only synthetic content; never preview real submissions in hosted tools."""
import shutil

import pytest
from reportlab.pdfgen import canvas

from mva_runner.render import inspect_pdf


@pytest.mark.skipif(not shutil.which("pdftotext") or not shutil.which("pdftoppm"), reason="Local PDF tools unavailable")
def test_shorter_regenerated_report_does_not_inherit_stale_preview_pages(tmp_path):
    path = tmp_path / "synthetic.pdf"
    for count in (2, 1):
        document = canvas.Canvas(str(path))
        for page in range(count):
            document.setFont("Helvetica", 24)
            document.drawString(50, 700, f"Synthetic report page {page + 1}")
            document.showPage()
        document.save()
        result = inspect_pdf(path, expected_pages=count)
        assert result["raster_pages_checked"] == count
    assert len(list((tmp_path / "synthetic_render").iterdir())) == 2
