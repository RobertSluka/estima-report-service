"""Orchestrates the full report-generation pipeline.

payload -> HTML (Jinja2) -> PDF (WeasyPrint) -> local storage

``meta.json`` is written only after every artifact succeeded, so a report is
never listed in a half-generated state: a PDF failure removes the directory
and propagates the error.
"""
from __future__ import annotations

import logging
import time
import uuid

from app.config import settings
from app.models import EvaluationPayload
from app.services import pdf, renderer, storage

logger = logging.getLogger("estima_report")


class ReportGenerationError(Exception):
    """Raised when a report cannot be generated."""


def generate_report(payload: EvaluationPayload, make_pdf: bool = True):
    """Render and persist a report, returning its :class:`ReportRecord`."""
    report_id = uuid.uuid4().hex
    started = time.perf_counter()

    style = payload.options.template or settings.DEFAULT_TEMPLATE
    language = payload.options.language or settings.DEFAULT_LANGUAGE

    try:
        html = renderer.render_html(payload)
    except renderer.TemplateNotFoundError as exc:
        raise ReportGenerationError(str(exc)) from exc

    record = storage.prepare_report(
        report_id=report_id,
        html=html,
        template=style,
        language=language,
        property_title=payload.property.title if payload.property else None,
    )

    if make_pdf:
        try:
            pdf.html_to_pdf(html, record.pdf_path, base_url=str(settings.ASSETS_DIR))
        except Exception:
            storage.discard_report(record)
            logger.exception(
                "report generation failed report_id=%s template=%s language=%s "
                "stage=pdf duration_ms=%.0f",
                report_id, style, language, (time.perf_counter() - started) * 1000,
            )
            raise

    storage.finalize_report(record)
    logger.info(
        "report generated report_id=%s template=%s language=%s pdf=%s duration_ms=%.0f",
        report_id, style, language, make_pdf, (time.perf_counter() - started) * 1000,
    )
    return record
