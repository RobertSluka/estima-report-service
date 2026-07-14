"""Local filesystem storage for generated reports.

Each report gets its own directory under ``REPORTS_DIR`` keyed by ``report_id``:

    reports/<report_id>/
        report.html
        report.pdf
        meta.json

This layout keeps artifacts grouped and makes it trivial to serve or clean them
up later. A database can replace ``meta.json`` when persistence is introduced.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from app.config import settings

HTML_FILENAME = "report.html"
PDF_FILENAME = "report.pdf"
META_FILENAME = "meta.json"


@dataclass
class ReportRecord:
    report_id: str
    status: str
    created_at: str
    template: str
    language: str
    property_title: Optional[str] = None

    @property
    def dir(self) -> Path:
        return settings.REPORTS_DIR / self.report_id

    @property
    def html_path(self) -> Path:
        return self.dir / HTML_FILENAME

    @property
    def pdf_path(self) -> Path:
        return self.dir / PDF_FILENAME


def _report_dir(report_id: str) -> Path:
    return settings.REPORTS_DIR / report_id


def save_report(
    report_id: str,
    html: str,
    pdf_bytes: Optional[bytes],
    template: str,
    language: str,
    property_title: Optional[str],
) -> ReportRecord:
    """Persist HTML, PDF, and metadata for a report; return its record."""
    directory = _report_dir(report_id)
    directory.mkdir(parents=True, exist_ok=True)

    (directory / HTML_FILENAME).write_text(html, encoding="utf-8")
    if pdf_bytes is not None:
        (directory / PDF_FILENAME).write_bytes(pdf_bytes)

    record = ReportRecord(
        report_id=report_id,
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        template=template,
        language=language,
        property_title=property_title,
    )
    (directory / META_FILENAME).write_text(
        json.dumps(asdict(record), indent=2), encoding="utf-8"
    )
    return record


def pdf_path_for(report_id: str) -> Path:
    return _report_dir(report_id) / PDF_FILENAME


def html_path_for(report_id: str) -> Path:
    return _report_dir(report_id) / HTML_FILENAME


def get_report(report_id: str) -> Optional[ReportRecord]:
    meta = _report_dir(report_id) / META_FILENAME
    if not meta.is_file():
        return None
    data = json.loads(meta.read_text(encoding="utf-8"))
    return ReportRecord(**data)


def list_reports() -> List[ReportRecord]:
    if not settings.REPORTS_DIR.is_dir():
        return []
    records: List[ReportRecord] = []
    for child in settings.REPORTS_DIR.iterdir():
        if child.is_dir():
            record = get_report(child.name)
            if record:
                records.append(record)
    records.sort(key=lambda r: r.created_at, reverse=True)
    return records
