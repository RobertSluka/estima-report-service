"""Tests for the Estima Academy landing page endpoints.

The page is public marketing content: no API key, served from STATIC_DIR,
and downloadable as a PDF rendered through the pdf.py isolation layer.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
ACADEMY_HTML = ROOT / "app" / "static" / "academy.html"


def _weasyprint_available() -> bool:
    try:
        importlib.import_module("weasyprint")
        return True
    except Exception:
        return False


def _client() -> TestClient:
    from app.main import app

    return TestClient(app)


def test_academy_page_is_served_without_api_key(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "API_KEY", "secret")  # must not gate /academy
    response = _client().get("/academy")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Estima Academy" in response.text
    assert "Make every valuation easier to explain" in response.text


def test_academy_page_contains_all_guides_and_disclaimer():
    html = ACADEMY_HTML.read_text(encoding="utf-8")
    numbers = re.findall(r'class="guide-num">(\d+)<', html)
    assert numbers == [str(n) for n in range(1, 19)]
    for title in [
        "How to Prepare a Data-Supported Property Valuation",
        "How to Select Genuinely Comparable Properties",
        "How to Explain an Estima Price Range to a Seller",
        "How Agencies Can Create a Consistent Valuation Standard",
    ]:
        assert title in html, f"missing guide: {title}"
    assert html.count("How Estima helps") == 18
    assert "do not represent a certified expert valuation" in html


def test_academy_download_returns_pdf_or_503():
    response = _client().get("/academy/download")
    if _weasyprint_available():
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert "estima-academy.pdf" in response.headers["content-disposition"]
        assert response.content.startswith(b"%PDF")
    else:
        assert response.status_code == 503
        assert "PDF engine unavailable" in response.json()["detail"]


def test_academy_missing_page_is_404(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "STATIC_DIR", tmp_path)
    client = _client()
    assert client.get("/academy").status_code == 404
    assert client.get("/academy/download").status_code == 404
