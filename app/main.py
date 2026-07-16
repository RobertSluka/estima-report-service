"""FastAPI application exposing the report generation endpoints."""
from __future__ import annotations

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from app import __version__
from app.config import settings
from app.models import EvaluationPayload, GenerateResponse, ReportInfo
from app.services import storage
from app.services.generator import ReportGenerationError, generate_report


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_dirs()
    yield


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


@app.post(
    "/reports/generate",
    response_model=GenerateResponse,
    status_code=201,
    tags=["reports"],
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


@app.get("/reports", response_model=list[ReportInfo], tags=["reports"])
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


@app.get("/reports/{report_id}", tags=["reports"])
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


@app.get("/reports/{report_id}/download", tags=["reports"])
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
