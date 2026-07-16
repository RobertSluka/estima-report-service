"""(Re)write the public-API surface snapshot used by the architecture tests.

The snapshot (``tests/openapi_snapshot.json``) is a deliberate projection of
the OpenAPI schema — paths, methods, parameter names, request-body presence,
response codes, and model property names. Descriptions and other prose are
excluded so documentation edits never trip the guardrail; a *surface* change
(new endpoint, renamed field, changed status code) always does.

Changing the public API therefore requires rerunning this script and letting
the snapshot diff show up in review:

    python scripts/update_openapi_snapshot.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "tests" / "openapi_snapshot.json"


def api_surface(schema: dict) -> dict:
    """Project an OpenAPI schema down to its compatibility-relevant surface."""
    surface: dict = {"paths": {}, "schemas": {}}
    for path, methods in sorted(schema.get("paths", {}).items()):
        for method, op in sorted(methods.items()):
            surface["paths"][f"{method.upper()} {path}"] = {
                "params": sorted(p["name"] for p in op.get("parameters", [])),
                "has_body": "requestBody" in op,
                "responses": sorted(op.get("responses", {})),
            }
    for name, model in sorted(
        schema.get("components", {}).get("schemas", {}).items()
    ):
        surface["schemas"][name] = sorted(model.get("properties", {}))
    return surface


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from app.main import app

    SNAPSHOT.write_text(
        json.dumps(api_surface(app.openapi()), indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
