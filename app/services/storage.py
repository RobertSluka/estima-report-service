"""Local filesystem storage for generated reports.

Each report gets its own directory under ``REPORTS_DIR`` keyed by ``report_id``:

    reports/<report_id>/
        report.html
        report.pdf
        meta.json

``meta.json`` is written last (see :func:`finalize_report`): a directory
without it is an in-progress or failed generation and is never listed, so a
report is only ever visible in a complete, consistent state.

This layout keeps artifacts grouped and makes it trivial to serve or clean them
up later. A database can replace ``meta.json`` when persistence is introduced.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from app.config import settings

HTML_FILENAME = "report.html"
PDF_FILENAME = "report.pdf"
META_FILENAME = "meta.json"

# report_id is always uuid4().hex; anything else is rejected before it can
# reach the filesystem (defense in depth against path tricks).
VALID_REPORT_ID = re.compile(r"^[0-9a-f]{32}$")


def is_valid_report_id(report_id: str) -> bool:
    return bool(VALID_REPORT_ID.fullmatch(report_id))


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
    if not is_valid_report_id(report_id):
        raise ValueError(f"Invalid report id: {report_id!r}")
    return settings.REPORTS_DIR / report_id


def prepare_report(
    report_id: str,
    html: str,
    template: str,
    language: str,
    property_title: Optional[str],
) -> ReportRecord:
    """Write the report directory and HTML, but not ``meta.json`` yet.

    The report stays invisible to :func:`get_report`/:func:`list_reports`
    until :func:`finalize_report` is called.
    """
    directory = _report_dir(report_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / HTML_FILENAME).write_text(html, encoding="utf-8")

    return ReportRecord(
        report_id=report_id,
        status="completed",
        created_at=datetime.now(timezone.utc).isoformat(),
        template=template,
        language=language,
        property_title=property_title,
    )


def finalize_report(record: ReportRecord) -> ReportRecord:
    """Write ``meta.json``, making the report visible and complete."""
    (record.dir / META_FILENAME).write_text(
        json.dumps(asdict(record), indent=2), encoding="utf-8"
    )
    return record


def discard_report(record: ReportRecord) -> None:
    """Remove a partially generated report directory after a failure."""
    shutil.rmtree(record.dir, ignore_errors=True)


def delete_report(report_id: str) -> bool:
    """Delete a report directory. Returns False when it does not exist."""
    directory = _report_dir(report_id)
    if not directory.is_dir():
        return False
    shutil.rmtree(directory)
    return True


def pdf_path_for(report_id: str) -> Path:
    return _report_dir(report_id) / PDF_FILENAME


def html_path_for(report_id: str) -> Path:
    return _report_dir(report_id) / HTML_FILENAME


def get_report(report_id: str) -> Optional[ReportRecord]:
    if not is_valid_report_id(report_id):
        return None
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
        if child.is_dir() and is_valid_report_id(child.name):
            record = get_report(child.name)
            if record:
                records.append(record)
    records.sort(key=lambda r: r.created_at, reverse=True)
    return records


def cleanup_expired(ttl_days: int) -> List[str]:
    """Delete reports whose ``created_at`` is older than ``ttl_days``.

    Returns the deleted report ids. A non-positive TTL is a no-op so the
    default configuration never removes anything.
    """
    if ttl_days <= 0:
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    deleted: List[str] = []
    for record in list_reports():
        try:
            created = datetime.fromisoformat(record.created_at)
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created < cutoff:
            if delete_report(record.report_id):
                deleted.append(record.report_id)
    return deleted
