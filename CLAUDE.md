# CLAUDE.md — estima-report-service

## What this repo is

A standalone FastAPI microservice that renders a prepared property-evaluation
JSON into an HTML/PDF real-estate report. It does **rendering only** — no
valuation, scraping, ML, scoring, or database work. Those live in sibling
repos on the Desktop: `estima-backend` (API/valuation), `estima-vision`
(image scoring), `estima-frontend` (scraper datasets).

## Architecture

Pipeline: payload → Jinja2 HTML → WeasyPrint PDF → local filesystem.
No database. Artifacts are written to `reports/<report_id>/`
(`report.html`, `report.pdf`, `meta.json`).

- `app/main.py` — FastAPI app + endpoints (`POST /reports/generate`,
  `GET /reports/{id}`, `GET /reports/{id}/download`, `GET /reports`, `GET /health`)
- `app/config.py` — env-driven `Settings` singleton (`REPORTS_DIR`,
  `TEMPLATES_DIR`, `DEFAULT_TEMPLATE`, `DEFAULT_LANGUAGE`, `PUBLIC_BASE_URL`, …)
- `app/models.py` — Pydantic v2 payload/response schemas (permissive: unknown
  fields ignored, missing fields degrade gracefully in templates)
- `app/services/renderer.py` — Jinja2 rendering + template resolution with
  fallback (requested language → default language → default style)
- `app/services/pdf.py` — WeasyPrint isolation layer; nothing else may import
  WeasyPrint directly (kept swappable for Playwright/Puppeteer)
- `app/services/storage.py` — local filesystem persistence
- `app/services/generator.py` — orchestrates the pipeline
- `app/services/formatting.py` — Jinja2 filters (money, area, percent, …)
- `app/static/index.html` — minimal UI served at `GET /` (path via `STATIC_DIR`)
- `app/templates/<style>/<language>/report.html` — new agencies/styles/languages
  are added by dropping in directories, **not** by code changes
- `samples/sample_evaluation.json` — canonical working payload example
- `scripts/render_local.py` — render the sample without a server
  (`--no-pdf` skips WeasyPrint, useful when native libs are missing)
- `tests/test_reports.py` — rendering/storage/API tests

## Commands

```bash
# Install (venv exists at .venv/)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # WeasyPrint needs native libs:
                                         # brew install pango gdk-pixbuf libffi

# Dev server
uvicorn app.main:app --reload            # docs at http://localhost:8000/docs
# or: .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8090  (.claude/launch.json)

# Docker (bundles all native PDF deps — preferred for PDF work)
docker compose up --build

# Tests (PDF tests auto-skip if WeasyPrint native libs are absent)
pip install pytest httpx
pytest -q

# Local render without server
python scripts/render_local.py samples/sample_evaluation.json
# End-to-end smoke against a running server
bash scripts/curl_examples.sh
```

- Lint/format: TODO — no ruff/flake8/black config exists in the repo.
- Build: none beyond Docker; no packaging config (no pyproject.toml).
- Database/migrations: none (filesystem storage only).

## Coding conventions

- Python with `from __future__ import annotations` and full type hints in
  every module.
- Module docstrings explain each file's role; short inline comments state
  constraints, not narration.
- Pinned dependencies in `requirements.txt` (`pkg==x.y.z`).
- `weasyprint==62.3` pairs with `pydyf==0.10.0` — never change one pin without
  the other (mismatch crashes with `'super' object has no attribute 'transform'`).
  estima-backend deliberately pins 65.1/0.12.1; don't copy pins across repos.
- Config only via `app.config.settings` (env-var overridable) — never read
  `os.getenv` elsewhere.
- Domain errors are custom exceptions (`ReportGenerationError`,
  `TemplateNotFoundError`) raised from lower-level causes.
- Tests use pytest fixtures + `monkeypatch`; an autouse fixture redirects
  `REPORTS_DIR` to a tmp dir so tests never touch real `reports/`.
- Templates/CSS: branding is injected via CSS variables in
  `app/templates/default/styles.css`; keep template logic in Jinja2 filters
  (`formatting.py`), not inline in templates.

## Do NOT without asking

- Add a database, queue, or any new persistent store — this service is
  deliberately filesystem-only.
- Add valuation/scraping/ML logic — that belongs in the sibling repos.
- Import WeasyPrint outside `app/services/pdf.py`.
- Add or upgrade dependencies, or unpin versions in `requirements.txt`.
- Delete or rewrite generated artifacts under `reports/` (contains real output).
- Modify production config or secrets; config changes go through
  `app/config.py` env vars only.
- Change the public API surface (paths, response shapes) — other services
  consume it.
- Modify the sibling repos (`estima-backend`, `estima-frontend`,
  `estima-vision`) while working on a report-service task.
- `git push` unless explicitly asked (origin: github.com/RobertSluka/estima-report-service, private).

## Required workflow

1. **Inspect** — read the relevant files (`app/`, `tests/`, README) before
   proposing or making changes. Never guess file structure or behavior.
2. **Plan** — restate the task as concrete acceptance criteria; for
   multi-file changes, write a short milestone plan and do one milestone
   at a time.
3. **Implement** — smallest change that meets the criteria; don't touch
   unrelated files. Verify with `pytest -q` (plus
   `python scripts/render_local.py samples/sample_evaluation.json --no-pdf`
   for template changes; use Docker when PDF output must be checked).
4. **Summarize** — end with the list of changed files, what changed in each,
   how it was verified, and anything that could not be verified and why.
