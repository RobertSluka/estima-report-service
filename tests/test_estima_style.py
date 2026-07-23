"""Tests for the "estima" template style (backend-aligned report design)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_SK = ROOT / "samples" / "sample_evaluation_sk.json"
SAMPLE_FULL = ROOT / "samples" / "sample_evaluation.json"


@pytest.fixture(autouse=True)
def isolated_reports_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "REPORTS_DIR", tmp_path / "reports")
    settings.ensure_dirs()
    yield


def _render(sample: Path, language: str) -> str:
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    payload = json.loads(sample.read_text(encoding="utf-8"))
    payload["options"] = {"template": "estima", "language": language}
    return render_html(EvaluationPayload.model_validate(payload))


def test_estima_sk_renders_slovak_chrome():
    html = _render(SAMPLE_SK, "sk")

    for probe in (
        "Odhad hodnoty nehnuteľnosti",
        "Realitná inteligencia",
        "Údaje o nehnuteľnosti",
        "Analýza trhu",
        "Porovnateľné inzeráty",
        "Záverečné odporúčanie",
        "Silné stránky",
    ):
        assert probe in html, f"missing sk chrome: {probe}"
    # No English template chrome leaks into the Slovak report.
    for absent in ("Property Details", "Market Analysis", "Final Recommendation"):
        assert absent not in html


def test_estima_sk_verdict_and_amounts():
    html = _render(SAMPLE_SK, "sk")

    # 268 000 asking vs 275 000 estimate is inside the ±3% band -> fair.
    assert 'verdict-pill v-fair' in html
    assert "Primeraná cena" in html
    # Backend-style amounts: narrow-space grouping, trailing currency.
    assert "275 000 EUR" in html
    assert "-7 000 EUR" in html  # signed difference vs asking


def test_estima_en_renders_english_chrome():
    html = _render(SAMPLE_FULL, "en")

    assert "Property Valuation Report" in html
    assert "Real Estate Intelligence" in html
    assert "Comparable listings" in html
    assert "Údaje" not in html


def test_estima_language_fallback_to_en():
    # 'de' has no estima template: falls back to estima/en, fully English.
    html = _render(SAMPLE_FULL, "de")
    assert "Property Valuation Report" in html
    assert "Odhad hodnoty" not in html


def test_estima_makes_no_semantic_vision_claims():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    payload = json.loads(SAMPLE_FULL.read_text(encoding="utf-8"))
    payload["options"] = {"template": "estima", "language": "en"}
    payload["vision_analysis"].update({
        "overall_condition_score": 0.9,
        "renovation_score": 0.85,
        "detected_features": ["Vision-detected premium sauna"],
        "price_adjustment": 0.03,
    })
    html = render_html(EvaluationPayload.model_validate(payload))

    assert "Listing Photo Quality" in html
    for forbidden in (
        "Overall condition",
        "Vision-detected premium sauna",
        "Condition-based price adjustment",
    ):
        assert forbidden not in html


def test_estima_thin_payload_shows_fallbacks():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    payload = {"options": {"template": "estima", "language": "en"}}
    html = render_html(EvaluationPayload.model_validate(payload))

    assert "Untitled property" in html
    assert "No photo analysis is available" in html
    assert "Location context is unavailable" in html
    assert "Not assessed" in html  # verdict without prices


# --------------------------------------------------------------------------- #
# New filters
# --------------------------------------------------------------------------- #
def test_amount_and_num_formatting():
    from app.services.formatting import amount, num, pct, signed_amount

    assert amount(195000, "EUR") == "195 000 EUR"
    assert amount(None) == "—"
    assert num(3482.4) == "3 482"
    assert num(72, 0, " m²") == "72 m²"
    assert signed_amount(-15000, "EUR") == "-15 000 EUR"
    assert signed_amount(15000, "EUR") == "+15 000 EUR"
    assert pct(-7.1, 1, True) == "-7.1 %"
    assert pct(7.14, 1, True) == "+7.1 %"


def test_verdict_key_thresholds():
    from app.services.formatting import verdict_key

    assert verdict_key(100, 110) == "undervalued"
    assert verdict_key(100, 90) == "overpriced"
    assert verdict_key(100, 102) == "fair"
    assert verdict_key(None, 100) == "unknown"
    assert verdict_key(0, 100) == "unknown"


def test_date_l10n():
    from datetime import date

    from app.services.formatting import date_l10n

    assert date_l10n(date(2026, 7, 16), "sk") == "16 júl 2026"
    assert date_l10n(date(2026, 7, 16), "en") == "16 Jul 2026"
    assert date_l10n(None) == "—"


def test_embed_image_policy():
    from app.services.formatting import embed_image

    placeholder = embed_image(None)
    assert placeholder.startswith("data:image/svg+xml;base64,")
    # data URIs pass through untouched.
    assert embed_image("data:image/png;base64,AAAA") == "data:image/png;base64,AAAA"
    # Non-public host is blocked by the SSRF policy -> placeholder, no raise.
    assert embed_image("http://127.0.0.1/internal.png") == placeholder
    # Unsupported scheme -> placeholder.
    assert embed_image("file:///etc/passwd") == placeholder


def test_index_svg_needs_three_points():
    from app.services.formatting import index_svg

    assert str(index_svg([])) == ""
    assert str(index_svg([{"period": "1Q", "value": 1.0}, {"period": "2Q", "value": 2.0}])) == ""
    svg = str(index_svg(
        [{"period": "1Q", "value": 100.0}, {"period": "2Q", "value": 110.0},
         {"period": "3Q", "value": 120.0}]
    ))
    assert svg.startswith("<svg") and "polyline" in svg


def test_estima_sk_renders_buy_vs_rent_subsection():
    html = _render(SAMPLE_SK, "sk")

    assert "Kúpa vs. nájom a investovanie" in html
    # Assumptions line carries the upstream numbers and sources.
    assert "268 000 EUR" in html  # NNBSP grouping from the amount filter
    assert "NBS regional price series, Bratislava Region" in html
    # Two-line wealth chart with the legend labels.
    assert "Nájom + investície" in html
    assert 'fill="#0e9f6e"' in html  # buyer line color only wealth_svg emits
    assert "Kúpa vychádza lepšie" in html


def test_estima_skips_buy_vs_rent_without_block():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    payload = json.loads(SAMPLE_SK.read_text(encoding="utf-8"))
    payload.pop("buy_vs_rent", None)
    payload["options"] = {"template": "estima", "language": "sk"}
    html = render_html(EvaluationPayload.model_validate(payload))

    assert "Kúpa vs. nájom a investovanie" not in html
