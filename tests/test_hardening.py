"""Tests for the correctness/safety hardening and ops behavior.

Covers: consistent state on PDF failure, report_id validation, payload size
limit, and the restricted asset fetcher used during PDF conversion. None of
these tests require WeasyPrint's native libraries.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_evaluation.json"


@pytest.fixture()
def sample_payload() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def isolated_reports_dir(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "REPORTS_DIR", tmp_path / "reports")
    settings.ensure_dirs()
    yield


# --------------------------------------------------------------------------- #
# Consistent state on PDF failure
# --------------------------------------------------------------------------- #
def test_pdf_failure_leaves_no_artifacts(sample_payload, monkeypatch):
    from app.config import settings
    from app.models import EvaluationPayload
    from app.services import pdf, storage
    from app.services.generator import generate_report

    def boom(html, output_path, base_url):
        raise RuntimeError("pdf backend exploded")

    monkeypatch.setattr(pdf, "html_to_pdf", boom)

    with pytest.raises(RuntimeError):
        generate_report(EvaluationPayload.model_validate(sample_payload))

    # No orphan directory, nothing listed as completed.
    assert storage.list_reports() == []
    assert list(settings.REPORTS_DIR.iterdir()) == []


def test_report_invisible_until_finalized(sample_payload):
    from app.models import EvaluationPayload
    from app.services import renderer, storage

    payload = EvaluationPayload.model_validate(sample_payload)
    record = storage.prepare_report(
        report_id="a" * 32,
        html=renderer.render_html(payload),
        template="default",
        language="en",
        property_title="t",
    )
    assert storage.get_report(record.report_id) is None
    assert storage.list_reports() == []

    storage.finalize_report(record)
    assert storage.get_report(record.report_id) is not None


# --------------------------------------------------------------------------- #
# report_id validation
# --------------------------------------------------------------------------- #
def test_invalid_report_ids_rejected():
    from app.services import storage

    for bad in ("", "not-a-uuid", "A" * 32, "..", "%2e%2e", "a" * 31, "a" * 33):
        assert storage.get_report(bad) is None
        with pytest.raises(ValueError):
            storage.pdf_path_for(bad)


def test_api_invalid_report_id_returns_404():
    from app.main import app

    client = TestClient(app)
    assert client.get("/reports/UPPERCASE-INVALID").status_code == 404
    assert client.get("/reports/UPPERCASE-INVALID/download").status_code == 404


# --------------------------------------------------------------------------- #
# Payload size limit
# --------------------------------------------------------------------------- #
def test_oversized_payload_rejected(sample_payload, monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "MAX_PAYLOAD_BYTES", 10)
    client = TestClient(app)
    resp = client.post("/reports/generate", json=sample_payload)
    assert resp.status_code == 413


# --------------------------------------------------------------------------- #
# Restricted asset fetcher (SSRF policy)
# --------------------------------------------------------------------------- #
def test_fetcher_blocks_unknown_schemes():
    from app.services.pdf import AssetFetchBlockedError, _restricted_url_fetcher

    with pytest.raises(AssetFetchBlockedError):
        _restricted_url_fetcher("ftp://example.com/logo.png")


def test_fetcher_blocks_non_public_hosts():
    from app.services.pdf import AssetFetchBlockedError, _validate_remote_url

    for url in (
        "http://127.0.0.1/internal",
        "http://10.0.0.5/logo.png",
        "http://192.168.1.1/x",
        "http://169.254.169.254/latest/meta-data",  # cloud metadata endpoint
        "http:///no-host",
    ):
        with pytest.raises(AssetFetchBlockedError):
            _validate_remote_url(url)


def test_fetcher_allows_public_hosts():
    from app.services.pdf import _validate_remote_url

    # Numeric public address: validates offline, no DNS needed.
    _validate_remote_url("https://93.184.216.34/image.jpg")


def test_fetcher_host_allowlist(monkeypatch):
    from app.config import settings
    from app.services.pdf import AssetFetchBlockedError, _validate_remote_url

    monkeypatch.setattr(settings, "ASSET_ALLOWED_HOSTS", ("93.184.216.34",))
    _validate_remote_url("https://93.184.216.34/ok.jpg")
    with pytest.raises(AssetFetchBlockedError):
        _validate_remote_url("https://8.8.8.8/blocked.jpg")


def test_fetcher_blocks_files_outside_assets_dir():
    from app.services.pdf import AssetFetchBlockedError, _validate_file_url

    with pytest.raises(AssetFetchBlockedError):
        _validate_file_url("file:///etc/passwd")


def test_fetcher_allows_files_inside_assets_dir():
    from app.config import settings
    from app.services.pdf import _validate_file_url

    inside = settings.ASSETS_DIR / "logo.png"
    _validate_file_url(inside.as_uri())


# --------------------------------------------------------------------------- #
# API key auth (opt-in via API_KEY env)
# --------------------------------------------------------------------------- #
def _generate_html_only(sample_payload):
    from app.models import EvaluationPayload
    from app.services.generator import generate_report

    return generate_report(
        EvaluationPayload.model_validate(sample_payload), make_pdf=False
    )


def test_api_key_disabled_by_default():
    from app.main import app

    client = TestClient(app)
    assert client.get("/reports").status_code == 200


def test_api_key_enforced_when_configured(sample_payload, monkeypatch):
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "API_KEY", "sekrit")
    client = TestClient(app)

    # /health and / stay open; /reports endpoints require the header.
    assert client.get("/health").status_code == 200
    assert client.get("/reports").status_code == 401
    assert client.post("/reports/generate", json=sample_payload).status_code == 401
    assert (
        client.get("/reports", headers={"X-API-Key": "wrong"}).status_code == 401
    )
    assert (
        client.get("/reports", headers={"X-API-Key": "sekrit"}).status_code == 200
    )


# --------------------------------------------------------------------------- #
# DELETE /reports/{id}
# --------------------------------------------------------------------------- #
def test_delete_disabled_without_api_key(sample_payload):
    from app.main import app

    record = _generate_html_only(sample_payload)
    client = TestClient(app)
    assert client.delete(f"/reports/{record.report_id}").status_code == 403


def test_delete_report_with_api_key(sample_payload, monkeypatch):
    from app.config import settings
    from app.main import app
    from app.services import storage

    monkeypatch.setattr(settings, "API_KEY", "sekrit")
    record = _generate_html_only(sample_payload)
    client = TestClient(app)
    headers = {"X-API-Key": "sekrit"}

    assert client.delete(f"/reports/{record.report_id}").status_code == 401
    assert (
        client.delete(f"/reports/{record.report_id}", headers=headers).status_code
        == 204
    )
    assert storage.get_report(record.report_id) is None
    assert (
        client.delete(f"/reports/{record.report_id}", headers=headers).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# Retention cleanup
# --------------------------------------------------------------------------- #
def test_cleanup_expired_removes_only_old_reports(sample_payload):
    from app.services import storage

    old = _generate_html_only(sample_payload)
    fresh = _generate_html_only(sample_payload)

    # Backdate the first report far past any TTL.
    meta_path = old.dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["created_at"] = "2020-01-01T00:00:00+00:00"
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    assert storage.cleanup_expired(0) == []  # disabled TTL never deletes
    deleted = storage.cleanup_expired(30)
    assert deleted == [old.report_id]
    assert storage.get_report(fresh.report_id) is not None
