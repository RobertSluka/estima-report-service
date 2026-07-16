"""Tests for per-language filter labels.

Label-emitting filters must follow the language of the template that actually
resolved: a Slovak template gets Slovak labels, and a fallback to the English
template must produce a fully English report — never a mixed one.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_evaluation.json"

# Minimal templates exercising label filters, no includes/sections needed.
_MINI_TEMPLATE = "<html>{{ true | yesno }}|{{ 100 | verdict_label(120) }}</html>"


@pytest.fixture(autouse=True)
def isolated_reports_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "REPORTS_DIR", tmp_path / "reports")
    settings.ensure_dirs()
    yield


def test_build_filters_localizes_labels():
    from app.services.formatting import build_filters

    en = build_filters("en")
    sk = build_filters("sk")

    assert en["yesno"](True) == "Yes"
    assert sk["yesno"](True) == "Áno"
    assert sk["yesno"](False) == "Nie"
    assert en["verdict_label"](100, 120) == "Underpriced"
    assert sk["verdict_label"](100, 120) == "Pod trhovou cenou"
    assert sk["confidence_label"](0.9) == "Vysoká"
    assert sk["similarity_band"](95) == "Veľmi vysoká"
    assert sk["investor_attractiveness"](7) == "Silná"
    assert sk["benchmark_type_label"]("realized_sale") == "Realizované predajné ceny"
    # Unknown language falls back to English labels.
    assert build_filters("de")["yesno"](True) == "Yes"


def test_none_handling_unchanged():
    from app.services.formatting import build_filters

    sk = build_filters("sk")
    assert sk["yesno"](None) == "—"
    assert sk["verdict_label"](None, 100) is None
    assert sk["similarity_band"](None) == "—"


def _render_with_templates(tmp_path, monkeypatch, requested_language):
    from app.config import settings
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    templates = tmp_path / "templates"
    (templates / "default" / "en").mkdir(parents=True)
    (templates / "default" / "sk").mkdir(parents=True)
    (templates / "default" / "en" / "report.html").write_text(
        _MINI_TEMPLATE, encoding="utf-8"
    )
    (templates / "default" / "sk" / "report.html").write_text(
        _MINI_TEMPLATE, encoding="utf-8"
    )
    monkeypatch.setattr(settings, "TEMPLATES_DIR", templates)

    payload = json.loads(SAMPLE.read_text(encoding="utf-8"))
    payload["options"] = {"template": "default", "language": requested_language}
    return render_html(EvaluationPayload.model_validate(payload))


def test_sk_template_gets_sk_labels(tmp_path, monkeypatch):
    html = _render_with_templates(tmp_path, monkeypatch, "sk")
    assert "Áno" in html
    assert "Pod trhovou cenou" in html


def test_language_fallback_keeps_labels_english(tmp_path, monkeypatch):
    # 'de' has no template: falls back to the en template, and the labels
    # must be English too — no mixed-language output.
    html = _render_with_templates(tmp_path, monkeypatch, "de")
    assert "Yes" in html
    assert "Underpriced" in html
    assert "Áno" not in html
