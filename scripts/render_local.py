#!/usr/bin/env python3
"""Render a report from a JSON file directly, without starting the API server.

Useful for iterating on templates. Writes the HTML (and PDF unless --no-pdf)
into the reports/ directory and prints the paths.

Usage:
    python scripts/render_local.py [path/to/evaluation.json] [--no-pdf]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make the repository importable when run as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.models import EvaluationPayload  # noqa: E402
from app.services.generator import generate_report  # noqa: E402


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    make_pdf = "--no-pdf" not in sys.argv

    sample = args[0] if args else str(ROOT / "samples" / "sample_evaluation.json")
    data = json.loads(Path(sample).read_text(encoding="utf-8"))

    settings.ensure_dirs()
    payload = EvaluationPayload.model_validate(data)
    record = generate_report(payload, make_pdf=make_pdf)

    print(f"report_id : {record.report_id}")
    print(f"html      : {record.html_path}")
    if make_pdf:
        print(f"pdf       : {record.pdf_path}")
    else:
        print("pdf       : (skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
