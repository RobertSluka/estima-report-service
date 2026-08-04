"""Tests for the "estima" template style (backend-aligned report design)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_SK = ROOT / "samples" / "sample_evaluation_sk.json"
SAMPLE_FULL = ROOT / "samples" / "sample_evaluation.json"
SAMPLE_KOSICE = ROOT / "samples" / "sample_kosice_odborarska.json"


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


def test_estima_photo_pages_with_per_image_metrics():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    img_a = "data:image/png;base64,AAAA"
    img_b = "data:image/png;base64,BBBB"
    payload = {
        "options": {"template": "estima", "language": "en"},
        "property": {"images": [img_a, img_b]},
        "vision_analysis": {
            "available": True,
            "photo_quality": 71, "brightness": 53, "sharpness": 67,
            "gallery_size": 2,
            "image_metrics": [
                {"url": img_a, "photo_quality": 70, "brightness": 51, "sharpness": 64},
                {"url": img_b, "photo_quality": 74, "brightness": 50, "sharpness": 61},
            ],
        },
    }
    html = render_html(EvaluationPayload.model_validate(payload))

    # One large card per listing photo, each with its own metric chips;
    # small galleries stay two-per-page (no compact class).
    assert html.count('class="photo-card"') == 2
    assert 'photo-card compact' not in html
    assert "Photo 1 / 2" in html and "Photo 2 / 2" in html
    assert "<strong>70</strong>/100" in html and "<strong>74</strong>/100" in html
    # The gallery-level result closes the section, after the photo cards.
    assert "Overall photo-quality result" in html
    assert html.rindex('class="photo-card"') < html.index("Overall photo-quality result")
    # The old end-of-report thumbnail gallery is gone.
    assert 'class="gallery"' not in html
    assert "Property Photos" not in html


def test_estima_photos_render_without_vision_block():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    payload = {
        "options": {"template": "estima", "language": "en"},
        "property": {"images": ["data:image/png;base64,AAAA"]},
    }
    html = render_html(EvaluationPayload.model_validate(payload))

    assert html.count('class="photo-card"') == 1
    # No per-photo metrics bar and no misleading "no analysis" fallback.
    assert "Overall photo-quality result" not in html
    assert "No photo analysis is available" not in html


def test_kosice_model_sample_renders(monkeypatch):
    """The Košice–Odborárska model example drives the full photo section."""
    from app.models import EvaluationPayload
    from app.services import formatting
    from app.services.renderer import render_html

    # Keep the test offline: the sample's 13 photos are remote bazos URLs.
    monkeypatch.setattr(
        formatting, "embed_image", lambda url: "data:image/png;base64,STUB"
    )

    payload = json.loads(SAMPLE_KOSICE.read_text(encoding="utf-8"))
    html = render_html(EvaluationPayload.model_validate(payload))

    assert "Predaj veľký 2 izbový byt" in html
    assert 'verdict-pill v-undervalued' in html  # 195k asking vs 210k estimate
    # 13 photos -> compact cards, three per page.
    assert html.count('class="photo-card compact"') == 13
    assert "Fotografia 1 / 13" in html
    assert "Celkové hodnotenie fotografií" in html
    assert "NBS – ceny rezidenčných nehnuteľností" in html
    # Payload-supplied condition assessment with its provenance footnote.
    assert "Orientačné posúdenie stavu (z fotografií inzerátu)" in html
    assert "Podlahy" in html and "Kúpeľňa a WC" in html
    assert "nejde o technickú obhliadku" in html


def test_condition_assessment_only_renders_when_supplied():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    base = {"options": {"template": "estima", "language": "en"}}
    html = render_html(EvaluationPayload.model_validate(base))
    assert "Indicative condition assessment" not in html

    base["condition_assessment"] = {
        "available": True,
        "source": "Agent visual review",
        "items": [
            {"element": "Floors", "state": "New", "note": "Laminate throughout."},
            {"element": "Walls", "state": "Renovated", "note": "Freshly painted."},
        ],
        "summary": "Fully renovated interior.",
    }
    html = render_html(EvaluationPayload.model_validate(base))
    assert "Indicative condition assessment" in html
    assert "Floors" in html and "Freshly painted." in html
    assert "not a technical inspection" in html
    assert "Agent visual review" in html


def test_benchmark_scope_and_period_are_rendered():
    """A district index must show the district it covers, never bare."""
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    payload = {
        "options": {"template": "estima", "language": "cs"},
        "currency": "CZK",
        "benchmarks": [
            {
                "name": "Estima local listing median",
                "benchmark_type": "listing_asking",
                "value_per_sqm": 184209,
                "source": "Estima listing index",
            },
            {
                "name": "Deloitte Real Index",
                "benchmark_type": "realized_sale",
                "value_per_sqm": 137900,
                "scope": "Praha 6",
                "period": "Q3 2024",
            },
        ],
    }
    html = render_html(EvaluationPayload.model_validate(payload))

    assert "Praha 6 · Q3 2024" in html
    # Callers that pack scope+period into `source` still get it rendered.
    assert "Estima listing index" in html


def test_listing_photos_appear_only_in_the_photo_quality_section():
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    img = "data:image/png;base64,AAAA"
    payload = {
        "options": {"template": "estima", "language": "en"},
        "property": {"title": "Cover title", "images": [img]},
    }
    html = render_html(EvaluationPayload.model_validate(payload))

    # The cover is typographic — the only photo in the document is the
    # section-03 card, which carries its own per-photo result.
    assert "cover-img" not in html
    assert html.count(img) == 1
    assert html.index(img) > html.index("Listing Photo Quality")


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
