"""Tests for the Estima Academy landing page endpoints.

The page is public marketing content: no API key, served from STATIC_DIR,
and downloadable as a PDF rendered through the pdf.py isolation layer. It ships
in English (academy.html) and Slovak (academy_sk.html); the served language
follows ?lang=, then the service default, then English.
"""
from __future__ import annotations

import importlib
import re
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
ACADEMY_HTML = STATIC / "academy.html"
ACADEMY_SK_HTML = STATIC / "academy_sk.html"


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


def test_academy_lang_query_selects_slovak():
    response = _client().get("/academy?lang=sk")
    assert response.status_code == 200
    assert "Aby sa každé ocenenie ľahšie vysvetľovalo" in response.text
    assert "Ako pomáha Estima" in response.text


def test_academy_default_language_follows_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "DEFAULT_LANGUAGE", "sk")
    # No ?lang= → the estima.sk deployment default (sk) is served.
    assert "Aby sa každé ocenenie" in _client().get("/academy").text
    # An explicit request still wins over the default.
    assert "Make every valuation" in _client().get("/academy?lang=en").text


def test_academy_unknown_language_falls_back_to_english():
    response = _client().get("/academy?lang=de")
    assert response.status_code == 200
    assert "Make every valuation easier to explain" in response.text


def test_academy_pages_contain_all_guides_and_disclaimer():
    for page, first_title, disclaimer in [
        (
            ACADEMY_HTML,
            "How to Prepare a Data-Supported Property Valuation",
            "do not represent a certified expert valuation",
        ),
        (
            ACADEMY_SK_HTML,
            "Ako pripraviť ocenenie nehnuteľnosti podložené dátami",
            "nepredstavujú znalecký posudok",
        ),
    ]:
        html = page.read_text(encoding="utf-8")
        numbers = re.findall(r'class="guide-num">(\d+)<', html)
        assert numbers == [str(n) for n in range(1, 19)], page.name
        assert first_title in html, page.name
        assert html.count('class="helps"') == 18, page.name
        assert disclaimer in html, page.name


def test_academy_download_returns_pdf_or_503():
    for lang, expected_name in [(None, "en"), ("sk", "sk")]:
        url = "/academy/download" + (f"?lang={lang}" if lang else "")
        response = _client().get(url)
        if _weasyprint_available():
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/pdf"
            assert (
                f"estima-academy-{expected_name}.pdf"
                in response.headers["content-disposition"]
            )
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
