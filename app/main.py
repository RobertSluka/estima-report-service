"""FastAPI application exposing the report generation endpoints."""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import __version__
from app.config import settings
from app.models import EvaluationPayload, GenerateResponse, ReportInfo
from app.services import storage
from app.services.generator import ReportGenerationError, generate_report

logger = logging.getLogger("estima_report")

RETENTION_SWEEP_SECONDS = 3600


async def _retention_loop() -> None:
    while True:
        deleted = await asyncio.to_thread(
            storage.cleanup_expired, settings.REPORTS_TTL_DAYS
        )
        if deleted:
            logger.info(
                "retention sweep deleted=%d ttl_days=%d",
                len(deleted), settings.REPORTS_TTL_DAYS,
            )
        await asyncio.sleep(RETENTION_SWEEP_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    retention_task = None
    if settings.REPORTS_TTL_DAYS > 0:
        retention_task = asyncio.create_task(_retention_loop())
    yield
    if retention_task is not None:
        retention_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await retention_task


def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    """Optional auth: enforced only when the API_KEY env var is set."""
    if settings.API_KEY and x_api_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


app = FastAPI(
    title="Estima Report Service",
    version=__version__,
    description=(
        "Generates professional HTML/PDF real estate reports from a prepared "
        "property evaluation JSON. This service does not perform valuation, "
        "scraping, or data ingestion."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def limit_payload_size(request: Request, call_next):
    # Content-Length is authoritative for JSON clients; chunked bodies are not
    # expected from the services that call this API.
    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > settings.MAX_PAYLOAD_BYTES:
        return JSONResponse(
            {"detail": "Payload too large"}, status_code=413
        )
    return await call_next(request)


def _base_url(request: Request) -> str:
    if settings.PUBLIC_BASE_URL:
        return settings.PUBLIC_BASE_URL
    return str(request.base_url).rstrip("/")


def _links(request: Request, report_id: str) -> tuple[str, str]:
    base = _base_url(request)
    return (
        f"{base}/reports/{report_id}",
        f"{base}/reports/{report_id}/download",
    )


@app.get("/health", tags=["system"])
def health() -> dict:
    return {"status": "ok", "version": __version__}


@app.get("/", include_in_schema=False)
def index():
    """Serve the minimal frontend UI."""
    index_file = settings.STATIC_DIR / "index.html"
    if not index_file.is_file():
        return HTMLResponse(
            "<h1>Estima Report Service</h1><p>API is running. "
            'See <a href="/docs">/docs</a>.</p>'
        )
    return FileResponse(str(index_file))


@app.get("/sample", tags=["system"])
def sample_payload():
    """Return the bundled demo evaluation JSON (used by the UI's 'Load sample')."""
    if not settings.SAMPLE_PATH.is_file():
        raise HTTPException(status_code=404, detail="Sample payload not found")
    return JSONResponse(json.loads(settings.SAMPLE_PATH.read_text(encoding="utf-8")))


# The Academy page ships in these languages; the filename per language is
# academy.html (en) / academy_<lang>.html (others).
ACADEMY_LANGUAGES = ("en", "sk")

# Academy PDF cache: {(lang, source mtime): pdf bytes} — regenerated only when
# that language's source page changes, so repeated downloads don't re-run
# WeasyPrint.
_academy_pdf_cache: dict[tuple[str, float], bytes] = {}


def _resolve_academy_language(lang: Optional[str]) -> str:
    """Requested language → service default → English, restricted to shipped pages."""
    for candidate in (lang, settings.DEFAULT_LANGUAGE, "en"):
        if candidate and candidate.lower() in ACADEMY_LANGUAGES:
            return candidate.lower()
    return "en"


def _academy_page_path(language: str) -> Path:
    filename = "academy.html" if language == "en" else f"academy_{language}.html"
    page = settings.STATIC_DIR / filename
    if not page.is_file():
        raise HTTPException(status_code=404, detail="Academy page not found")
    return page


@app.get("/academy", tags=["academy"])
def academy_page(lang: Optional[str] = None):
    """Serve the Estima Academy landing page (valuation guidance for agents).

    Language follows ``?lang=`` (en/sk), otherwise the service default; unknown
    values fall back to English.
    """
    language = _resolve_academy_language(lang)
    return FileResponse(
        str(_academy_page_path(language)), media_type="text/html"
    )


@app.get("/academy/download", tags=["academy"])
def academy_download(lang: Optional[str] = None) -> Response:
    """Download the Estima Academy landing page as a PDF (see /academy for lang)."""
    language = _resolve_academy_language(lang)
    page = _academy_page_path(language)
    cache_key = (language, page.stat().st_mtime)
    pdf_bytes = _academy_pdf_cache.get(cache_key)
    if pdf_bytes is None:
        try:
            from app.services.pdf import html_to_pdf

            with tempfile.TemporaryDirectory() as tmp:
                output = Path(tmp) / "estima-academy.pdf"
                html_to_pdf(
                    page.read_text(encoding="utf-8"),
                    output,
                    base_url=str(settings.STATIC_DIR),
                )
                pdf_bytes = output.read_bytes()
        except Exception as exc:
            # Most likely WeasyPrint's native libraries are absent on the host;
            # the page itself stays available at /academy.
            raise HTTPException(
                status_code=503, detail=f"PDF engine unavailable: {exc}"
            ) from exc
        # Drop only this language's stale entry; keep the other language cached.
        for key in [k for k in _academy_pdf_cache if k[0] == language]:
            del _academy_pdf_cache[key]
        _academy_pdf_cache[cache_key] = pdf_bytes
    filename = f"estima-academy-{language}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )


@app.post(
    "/reports/generate",
    response_model=GenerateResponse,
    status_code=201,
    tags=["reports"],
    dependencies=[Depends(require_api_key)],
)
def create_report(payload: EvaluationPayload, request: Request) -> GenerateResponse:
    """Generate an HTML + PDF report from an evaluation payload."""
    try:
        record = generate_report(payload)
    except ReportGenerationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - surfaced as 500 to the client
        raise HTTPException(
            status_code=500, detail=f"Report generation failed: {exc}"
        ) from exc

    html_url, pdf_url = _links(request, record.report_id)
    return GenerateResponse(
        report_id=record.report_id,
        status=record.status,
        html_url=html_url,
        pdf_url=pdf_url,
        created_at=record.created_at,
    )


@app.get(
    "/reports",
    response_model=list[ReportInfo],
    tags=["reports"],
    dependencies=[Depends(require_api_key)],
)
def list_all_reports(request: Request) -> list[ReportInfo]:
    """List previously generated reports (newest first)."""
    result = []
    for record in storage.list_reports():
        html_url, pdf_url = _links(request, record.report_id)
        result.append(
            ReportInfo(
                report_id=record.report_id,
                status=record.status,
                created_at=record.created_at,
                html_url=html_url,
                pdf_url=pdf_url,
                template=record.template,
                language=record.language,
                property_title=record.property_title,
            )
        )
    return result


@app.get(
    "/reports/{report_id}", tags=["reports"], dependencies=[Depends(require_api_key)]
)
def get_report(report_id: str, request: Request):
    """Return the rendered HTML preview for a report.

    Pass ``?format=json`` to get the report metadata instead of the HTML body.
    """
    record = storage.get_report(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")

    if request.query_params.get("format") == "json":
        html_url, pdf_url = _links(request, report_id)
        return ReportInfo(
            report_id=record.report_id,
            status=record.status,
            created_at=record.created_at,
            html_url=html_url,
            pdf_url=pdf_url,
            template=record.template,
            language=record.language,
            property_title=record.property_title,
        )

    html_path = storage.html_path_for(report_id)
    if not html_path.is_file():
        raise HTTPException(status_code=404, detail="Report HTML not found")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get(
    "/reports/{report_id}/download",
    tags=["reports"],
    dependencies=[Depends(require_api_key)],
)
def download_report(report_id: str):
    """Download the generated PDF for a report."""
    record = storage.get_report(report_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Report not found")

    pdf_path = storage.pdf_path_for(report_id)
    if not pdf_path.is_file():
        raise HTTPException(status_code=404, detail="Report PDF not found")

    filename = f"estima-report-{report_id}.pdf"
    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=filename,
    )


@app.delete(
    "/reports/{report_id}",
    status_code=204,
    tags=["reports"],
    dependencies=[Depends(require_api_key)],
)
def delete_report(report_id: str) -> Response:
    """Delete a report and its artifacts.

    Deletion is only available when the service is configured with an API key
    — an unauthenticated deployment must not allow destructive operations.
    """
    if not settings.API_KEY:
        raise HTTPException(
            status_code=403, detail="Deletion is disabled: no API_KEY configured"
        )
    if storage.get_report(report_id) is None:
        raise HTTPException(status_code=404, detail="Report not found")
    storage.delete_report(report_id)
    logger.info("report deleted report_id=%s", report_id)
    return Response(status_code=204)
