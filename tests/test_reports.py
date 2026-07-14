"""Tests for rendering, storage, and the HTTP API.

Run with:  pytest -q

PDF-dependent paths are skipped automatically if WeasyPrint's native libraries
are not installed on the host, so the core logic can be tested anywhere.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_evaluation.json"
SAMPLE_MINIMAL = ROOT / "samples" / "sample_minimal_sale.json"
SAMPLE_RENT = ROOT / "samples" / "sample_rent.json"
SAMPLE_SK = ROOT / "samples" / "sample_evaluation_sk.json"


def _weasyprint_available() -> bool:
    try:
        importlib.import_module("weasyprint")
        return True
    except Exception:
        return False


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def sample_payload() -> dict:
    return _load(SAMPLE)


@pytest.fixture(autouse=True)
def isolated_reports_dir(tmp_path, monkeypatch):
    """Point storage at a temp dir so tests never touch real reports/."""
    from app.config import settings

    monkeypatch.setattr(settings, "REPORTS_DIR", tmp_path / "reports")
    settings.ensure_dirs()
    yield


def _render(path: Path) -> str:
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    return render_html(EvaluationPayload.model_validate(_load(path)))


def test_render_full_sale_contains_all_sections(sample_payload):
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    html = render_html(EvaluationPayload.model_validate(sample_payload))

    for heading in [
        "Executive Summary",
        "Property Details",
        "Market Valuation",
        "Comparable Listings",
        "Market Benchmarks",
        "Market Statistics",
        "Rent &amp; Investment Analysis",
        "Listing Photo Quality",
        "Location &amp; Nearby Facilities",
        "Risk &amp; Due Diligence Checklist",
        "Final Recommendation",
        "Methodology &amp; Disclaimer",
    ]:
        assert heading in html, f"missing section: {heading}"

    # Sample data rendered through filters/derived logic.
    assert "€572,000" in html  # estimated value
    assert "Kreuzberg" in html
    assert "Underpriced" in html  # verdict derived from list_price vs estimate
    assert "Very high" in html  # similarity band, not a raw percentage


def test_render_minimal_sale_hides_optional_sections():
    html = _render(SAMPLE_MINIMAL)

    assert "Executive Summary" in html
    assert "Property Details" in html
    assert "Market Valuation" in html
    assert "Comparable Listings" in html
    assert "Final Recommendation" in html
    assert "Methodology &amp; Disclaimer" in html

    for heading in [
        "Market Benchmarks",
        "Market Statistics",
        "Rent &amp; Investment Analysis",
        "Listing Photo Quality",
        "Location &amp; Nearby Facilities",
        "Risk &amp; Due Diligence Checklist",
    ]:
        assert heading not in html, f"section should be hidden: {heading}"

    assert "Photo-quality analysis was not available for this report." in html
    assert "Location and nearby-facility data was not available for this report." in html


def test_vision_section_makes_no_semantic_claims(sample_payload):
    """Photo-quality wording only: the vision section must never present
    condition/renovation/detected-room claims or a condition price adjustment,
    even when a (legacy) payload still carries those deprecated fields."""
    sample_payload["vision_analysis"].update({
        "overall_condition_score": 0.9,
        "renovation_score": 0.85,
        "detected_features": ["Vision-detected premium sauna"],
        "price_adjustment": 0.03,
    })
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    html = render_html(EvaluationPayload.model_validate(sample_payload))

    assert "Listing Photo Quality" in html
    for forbidden in (
        "Overall condition",
        "Renovation / luxury",
        "Detected rooms / features",
        "Vision-detected premium sauna",
        "Condition-based price adjustment",
    ):
        assert forbidden not in html, f"unsupported claim rendered: {forbidden}"
    # The scope note must separate photo quality from property condition.
    assert "not an assessment of the property" in html


def test_render_sk_sample_market_statistics_marks_subject():
    html = _render(SAMPLE_SK)

    assert "Market Statistics" in html
    assert "Bratislava Region, Slovakia" in html
    assert "National Bank of Slovakia" in html
    # Subject property is marked in red on the trend chart and the
    # distribution strip.
    assert 'class="chart-subject-dot"' in html
    assert 'class="range-subject-dot"' in html
    assert "This property" in html


def test_line_chart_geometry():
    from app.services.formatting import line_chart

    series = [{"period": "1Q", "value": 100.0}, {"period": "2Q", "value": 200.0}]

    # Too few usable points -> no chart.
    assert line_chart([]) is None
    assert line_chart([{"period": "1Q", "value": 100.0}]) is None
    assert line_chart([{"period": "1Q", "value": None}, {"period": "2Q", "value": None}]) is None

    chart = line_chart(series, subject_value=150.0)
    assert chart is not None
    # Subject dot sits at the last x position, vertically inside the plot.
    assert chart["subject"]["x"] == chart["last"]["x"]
    assert chart["pad_top"] < chart["subject"]["y"] < chart["baseline"]

    # A subject far above the series still lands inside the plot because the
    # y-domain expands to include it.
    chart = line_chart(series, subject_value=400.0)
    assert chart["pad_top"] <= chart["subject"]["y"] <= chart["baseline"]


def test_render_rent_property_has_no_rent_investment_section():
    html = _render(SAMPLE_RENT)

    assert "Property Rental Report" in html
    assert "Executive Summary" in html
    assert "Listing Photo Quality" in html
    assert "Location &amp; Nearby Facilities" in html
    assert "Market Benchmarks" in html
    assert "Rent &amp; Investment Analysis" not in html


def test_generate_html_only_persists_files(sample_payload):
    from app.models import EvaluationPayload
    from app.services import storage
    from app.services.generator import generate_report

    record = generate_report(
        EvaluationPayload.model_validate(sample_payload), make_pdf=False
    )
    assert record.html_path.is_file()

    fetched = storage.get_report(record.report_id)
    assert fetched is not None
    assert fetched.property_title == "Bright 3-Room Apartment with Balcony"
    assert fetched.template == "default"


def test_api_missing_report_returns_404():
    from app.main import app

    client = TestClient(app)
    assert client.get("/reports/does-not-exist").status_code == 404
    assert client.get("/reports/does-not-exist/download").status_code == 404


def test_health():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.skipif(
    not _weasyprint_available(), reason="WeasyPrint native libs not installed"
)
def test_api_full_generate_flow(sample_payload):
    from app.main import app

    client = TestClient(app)
    resp = client.post("/reports/generate", json=sample_payload)
    assert resp.status_code == 201
    body = resp.json()
    report_id = body["report_id"]

    assert client.get(f"/reports/{report_id}").status_code == 200

    pdf = client.get(f"/reports/{report_id}/download")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content[:4] == b"%PDF"
