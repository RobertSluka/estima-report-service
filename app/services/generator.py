"""Orchestrates the full report-generation pipeline.

payload -> HTML (Jinja2) -> PDF (WeasyPrint) -> local storage
"""
from __future__ import annotations

import uuid

from app.config import settings
from app.models import EvaluationPayload
from app.services import pdf, renderer, storage


class ReportGenerationError(Exception):
    """Raised when a report cannot be generated."""


def generate_report(payload: EvaluationPayload, make_pdf: bool = True):
    """Render and persist a report, returning its :class:`ReportRecord`."""
    report_id = uuid.uuid4().hex

    style = payload.options.template or settings.DEFAULT_TEMPLATE
    language = payload.options.language or settings.DEFAULT_LANGUAGE

    try:
        html = renderer.render_html(payload)
    except renderer.TemplateNotFoundError as exc:
        raise ReportGenerationError(str(exc)) from exc

    record = storage.save_report(
        report_id=report_id,
        html=html,
        pdf_bytes=None,  # PDF written separately below to avoid buffering it
        template=style,
        language=language,
        property_title=payload.property.title if payload.property else None,
    )

    if make_pdf:
        pdf.html_to_pdf(
            html,
            record.pdf_path,
            base_url=str(settings.ASSETS_DIR),
        )

    return record
