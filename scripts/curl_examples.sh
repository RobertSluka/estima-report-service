#!/usr/bin/env bash
# Sample requests against a running Estima report service.
#
#   1. Start the API:   uvicorn app.main:app --reload
#   2. Run this script: bash scripts/curl_examples.sh
#
# Requires: curl, and (optionally) jq for pretty output / id extraction.
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
SAMPLE="${SAMPLE:-samples/sample_evaluation.json}"

echo "==> Health check"
curl -sS "${BASE_URL}/health"; echo

echo
echo "==> POST /reports/generate"
RESPONSE=$(curl -sS -X POST "${BASE_URL}/reports/generate" \
    -H "Content-Type: application/json" \
    --data-binary "@${SAMPLE}")
echo "${RESPONSE}"

# Extract the report id (uses jq if available, falls back to grep/sed).
if command -v jq >/dev/null 2>&1; then
    REPORT_ID=$(echo "${RESPONSE}" | jq -r '.report_id')
else
    REPORT_ID=$(echo "${RESPONSE}" | grep -o '"report_id"[^,]*' | sed 's/.*: *"//; s/"//')
fi
echo
echo "report_id = ${REPORT_ID}"

echo
echo "==> GET /reports/{id}?format=json (metadata)"
curl -sS "${BASE_URL}/reports/${REPORT_ID}?format=json"; echo

echo
echo "==> GET /reports/{id} (HTML preview -> preview.html)"
curl -sS "${BASE_URL}/reports/${REPORT_ID}" -o preview.html
echo "saved preview.html"

echo
echo "==> GET /reports/{id}/download (PDF -> report.pdf)"
curl -sS "${BASE_URL}/reports/${REPORT_ID}/download" -o report.pdf
echo "saved report.pdf"
