# Estima Report Service

A standalone microservice that turns a **prepared property evaluation JSON** into
a professional real estate **HTML/PDF report**.

> This service only *renders reports*. It does **not** perform valuation,
> scraping, ML, market scoring, or database ingestion. It consumes a completed
> evaluation document (produced elsewhere) and generates the report.

## Features

- **FastAPI** JSON API with three core endpoints.
- **Jinja2** templates, organized as `templates/<style>/<language>/` so new
  agencies, languages, and report styles are added by dropping in directories —
  no code changes.
- **WeasyPrint** HTML → PDF conversion (isolated behind `app/services/pdf.py`,
  so it can later be swapped for Playwright/Puppeteer).
- **Local file storage** under `reports/<report_id>/` (`report.html`,
  `report.pdf`, `meta.json`). No database required.
- **Optional agency branding** (logo, colors, agent contact).
- **Dockerfile** + **docker-compose.yml** with all native PDF dependencies.

## API

| Method | Path                             | Description                                   |
| ------ | -------------------------------- | --------------------------------------------- |
| POST   | `/reports/generate`              | Generate HTML+PDF from an evaluation payload  |
| GET    | `/reports/{report_id}`           | HTML preview (`?format=json` for metadata)    |
| GET    | `/reports/{report_id}/download`  | Download the generated PDF                    |
| GET    | `/reports`                       | List generated reports (newest first)         |
| GET    | `/health`                        | Health check                                  |

`POST /reports/generate` returns:

```json
{
  "report_id": "…",
  "status": "completed",
  "html_url": "http://localhost:8000/reports/…",
  "pdf_url": "http://localhost:8000/reports/…/download",
  "created_at": "2026-07-03T12:00:00Z"
}
```

Interactive API docs are available at `/docs` when the server is running.

## Report sections

The `default` template renders:

1. Cover page
2. Property overview
3. Market comparison
4. Comparable listings
5. Recommended price range
6. Location & amenities
7. Image / condition analysis
8. Final recommendation for the agent

## Payload

The full schema is defined in [`app/models.py`](app/models.py) and a complete
working example lives in
[`samples/sample_evaluation.json`](samples/sample_evaluation.json). Top-level
keys: `property`, `pricing`, `valuation`, `comparables`, `location`,
`image_analysis`, `summary`, optional `branding`, and `options`
(`template` / `language`). The schema is permissive — unknown fields are ignored,
and missing fields degrade gracefully in the template.

## Run with Docker (recommended)

WeasyPrint needs native libraries; the image bundles them.

```bash
docker compose up --build
# → http://localhost:8000/docs

curl -X POST http://localhost:8000/reports/generate \
  -H "Content-Type: application/json" \
  --data-binary @samples/sample_evaluation.json
```

Generated reports persist in the `reports-data` Docker volume.

## Run locally (without Docker)

WeasyPrint's native deps must be present on the host (macOS:
`brew install pango gdk-pixbuf libffi`; Debian/Ubuntu: `apt-get install
libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev`).

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Local scripts

```bash
# Render the sample straight to reports/ (skip PDF with --no-pdf; handy while
# iterating on templates without native PDF deps installed):
python scripts/render_local.py samples/sample_evaluation.json

# Exercise a running server end-to-end (generate, preview, download):
bash scripts/curl_examples.sh
```

## Tests

```bash
pip install pytest httpx
pytest -q
```

PDF-dependent tests are skipped automatically when WeasyPrint's native libraries
are not installed, so the rendering/storage/API logic can be tested anywhere.

## Configuration

All settings ([`app/config.py`](app/config.py)) can be overridden via env vars:

| Variable            | Default              | Purpose                                  |
| ------------------- | -------------------- | ---------------------------------------- |
| `REPORTS_DIR`       | `./reports`          | Where HTML/PDF artifacts are written     |
| `TEMPLATES_DIR`     | `./app/templates`    | Template root                            |
| `ASSETS_DIR`        | `./app/assets`       | Static assets (fonts, logos)             |
| `DEFAULT_TEMPLATE`  | `default`            | Template style when payload omits one    |
| `DEFAULT_LANGUAGE`  | `en`                 | Language when payload omits one          |
| `PUBLIC_BASE_URL`   | *(request base URL)* | Base URL used in returned links          |

## Project layout

```
app/
  main.py                # FastAPI app + endpoints
  config.py              # env-driven settings
  models.py              # Pydantic payload + response schemas
  services/
    renderer.py          # Jinja2 HTML rendering + template resolution
    pdf.py               # HTML -> PDF (WeasyPrint, swappable)
    storage.py           # local filesystem storage
    generator.py         # pipeline: payload -> HTML -> PDF -> storage
    formatting.py        # Jinja2 filters (money, area, percent, …)
  templates/
    default/
      styles.css         # shared print stylesheet (branding via CSS vars)
      en/report.html     # default English template
  assets/                # fonts / logos (mounted into templates)
samples/sample_evaluation.json
scripts/render_local.py
scripts/curl_examples.sh
tests/test_reports.py
Dockerfile
docker-compose.yml
```

## Extending

- **New agency / style:** add `app/templates/<style>/<language>/report.html`
  (reuse or fork `styles.css`) and pass `options.template = "<style>"`.
- **New language:** add `app/templates/<style>/<lang>/report.html`; the renderer
  falls back to the default language, then the default style, if a localization
  is missing.
- **Different PDF engine:** replace `app/services/pdf.py` — nothing else depends
  on WeasyPrint directly.
