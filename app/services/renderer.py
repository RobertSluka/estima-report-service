"""HTML rendering via Jinja2.

Templates are organized as ``templates/<style>/<language>/report.html`` with an
``en`` fallback, so new agencies, styles, and languages can be added by dropping
in directories — no code changes required.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings
from app.models import EvaluationPayload
from app.services.formatting import FILTERS


class TemplateNotFoundError(Exception):
    """Raised when the requested template style cannot be resolved."""


def _resolve_template(style: str, language: str) -> str:
    """Return a loader-relative path to ``report.html`` for style/language.

    Falls back to the default language, then the default style, so a missing
    localization never breaks generation.
    """
    templates_dir = settings.TEMPLATES_DIR
    candidates = [
        Path(style) / language / "report.html",
        Path(style) / settings.DEFAULT_LANGUAGE / "report.html",
        Path(settings.DEFAULT_TEMPLATE) / language / "report.html",
        Path(settings.DEFAULT_TEMPLATE) / settings.DEFAULT_LANGUAGE / "report.html",
    ]
    for candidate in candidates:
        if (templates_dir / candidate).is_file():
            return candidate.as_posix()
    raise TemplateNotFoundError(
        f"No report template found for style='{style}' language='{language}' "
        f"under {templates_dir}"
    )


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(settings.TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(FILTERS)
    return env


def render_html(payload: EvaluationPayload) -> str:
    """Render the evaluation payload to a complete HTML document string."""
    style = payload.options.template or settings.DEFAULT_TEMPLATE
    language = payload.options.language or settings.DEFAULT_LANGUAGE

    template_path = _resolve_template(style, language)
    env = _build_env()
    template = env.get_template(template_path)

    generated_at = payload.generated_at or datetime.now(timezone.utc)

    context: Dict[str, Any] = {
        "report_title": payload.report_title or "Property Valuation Report",
        "generated_at": generated_at,
        "property": payload.property,
        "pricing": payload.pricing,
        "valuation": payload.valuation,
        "comparables": payload.comparables,
        "benchmarks": payload.benchmarks,
        "market_statistics": payload.market_statistics,
        "rent_investment": payload.rent_investment,
        "location_facilities": payload.location_facilities,
        "vision_analysis": payload.vision_analysis,
        "risk": payload.risk,
        "summary": payload.summary,
        "methodology": payload.methodology,
        "branding": payload.branding,
        "currency": payload.pricing.currency if payload.pricing else "EUR",
    }
    return template.render(**context)
