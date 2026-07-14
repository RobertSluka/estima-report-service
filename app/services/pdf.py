"""HTML → PDF conversion.

WeasyPrint is used because it renders print-oriented CSS well and runs headless
in a container without a browser engine. The conversion is isolated behind this
module so it can later be swapped for Playwright/Puppeteer without touching the
rest of the service.
"""
from __future__ import annotations

from pathlib import Path


def html_to_pdf(html: str, output_path: Path, base_url: str) -> Path:
    """Render ``html`` to a PDF file at ``output_path``.

    ``base_url`` lets WeasyPrint resolve relative asset references (fonts,
    local images) contained in the HTML/CSS.
    """
    # Imported lazily so importing the package (e.g. for tests that only render
    # HTML) does not require WeasyPrint's native dependencies to be installed.
    from weasyprint import HTML

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html, base_url=base_url).write_pdf(str(output_path))
    return output_path
