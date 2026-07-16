"""Contract tests against estima-backend's report schema.

models.py promises that this service's field names are aligned with
estima-backend's internal report schema so a live integration needs no
translation layer. These tests make that promise executable:

1. ``ALIGNED_FIELDS`` lists, per model pair, the leaf fields both sides share.
   Each must exist in this service's models AND in the checked-in snapshot of
   backend field names (``backend_contract_fields.json``).
2. When the sibling repo is present on disk (developer machines), the snapshot
   is re-derived from the live schema and compared — a backend rename fails
   here first, with ``scripts/refresh_backend_contract.py`` as the remedy.
3. A fixture payload written strictly in the shared vocabulary must validate
   and render.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "backend_contract_fields.json"
CONTRACT_SAMPLE = ROOT / "samples" / "sample_backend_contract.json"
BACKEND_SCHEMA = (
    ROOT.parent / "estima-backend" / "src" / "services" / "reports" / "schema.py"
)

# (our model name, backend model name) -> shared leaf-field names.
ALIGNED_FIELDS = {
    ("PropertyMetadata", "Property"): [
        "title", "locality", "address", "property_type", "deal_type", "layout",
        "floor_area", "land_area", "floor", "source", "source_url",
        "days_on_market", "first_seen_at", "last_seen_at",
    ],
    ("Comparable", "Comparable"): [
        "label", "locality", "layout", "floor_area", "price", "price_per_sqm",
        "price_difference_vs_subject", "similarity_score", "source_url",
        "is_subject", "is_median",
    ],
    ("MarketBenchmark", "MarketBenchmark"): ["name", "value_per_sqm"],
    ("VisionAnalysis", "VisionAnalysis"): [
        "available", "gallery_size", "observations", "summary",
    ],
    ("ReportSummary", "Recommendation"): ["strengths", "risks", "next_steps"],
    ("Valuation", "MarketAnalysis"): [
        "estimated_value", "local_median_price", "local_median_price_per_sqm",
    ],
}


def _snapshot() -> dict:
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


def test_aligned_fields_exist_on_both_sides():
    from app import models

    backend = _snapshot()
    for (our_name, backend_name), fields in ALIGNED_FIELDS.items():
        ours = getattr(models, our_name).model_fields
        theirs = backend[backend_name]
        for field in fields:
            assert field in ours, f"{our_name}.{field} missing in this service"
            assert field in theirs, (
                f"{backend_name}.{field} missing in estima-backend snapshot — "
                "backend renamed a shared field; update ALIGNED_FIELDS or the "
                "backend, then rerun scripts/refresh_backend_contract.py"
            )


@pytest.mark.skipif(
    not BACKEND_SCHEMA.is_file(),
    reason="sibling estima-backend repo not available (e.g. CI)",
)
def test_snapshot_matches_live_backend_schema():
    spec = importlib.util.spec_from_file_location(
        "refresh_backend_contract", ROOT / "scripts" / "refresh_backend_contract.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    live = module.extract_model_fields(BACKEND_SCHEMA)
    assert live == _snapshot(), (
        "estima-backend's report schema drifted from the checked-in snapshot; "
        "run: python scripts/refresh_backend_contract.py"
    )


def test_contract_sample_validates_and_renders(tmp_path, monkeypatch):
    from app.config import settings
    from app.models import EvaluationPayload
    from app.services.renderer import render_html

    monkeypatch.setattr(settings, "REPORTS_DIR", tmp_path / "reports")

    payload = EvaluationPayload.model_validate(
        json.loads(CONTRACT_SAMPLE.read_text(encoding="utf-8"))
    )
    html = render_html(payload)

    assert "Praha 4" in html
    assert "Deloitte Real Index" in html
    assert "CZK 8,900,000" in html  # estimated value through the money filter
    assert "Comparable Listings" in html
    assert "Final Recommendation" in html
