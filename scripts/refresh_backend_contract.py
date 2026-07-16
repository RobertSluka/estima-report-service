"""Refresh the estima-backend field-name snapshot used by the contract tests.

Reads the sibling repo's report schema (``estima-backend/src/services/reports/
schema.py``) via AST — no backend imports, so its dependencies are never
needed — and writes the per-model field names to
``tests/backend_contract_fields.json``.

Run this after estima-backend changes its report schema:

    python scripts/refresh_backend_contract.py [path-to-schema.py]

The diff of the snapshot then shows exactly which shared fields moved, and
``tests/test_backend_contract.py`` fails if a field this service relies on
disappeared.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = (
    ROOT.parent / "estima-backend" / "src" / "services" / "reports" / "schema.py"
)
SNAPSHOT = ROOT / "tests" / "backend_contract_fields.json"


def extract_model_fields(schema_path: Path) -> dict:
    """Map class name -> sorted annotated field names for every class.

    Only annotated assignments count, which naturally captures pydantic model
    fields and skips str-enum members.
    """
    tree = ast.parse(schema_path.read_text(encoding="utf-8"))
    models = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields = [
            stmt.target.id
            for stmt in node.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        ]
        if fields:
            models[node.name] = sorted(fields)
    return models


def main() -> None:
    schema = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SCHEMA
    if not schema.is_file():
        sys.exit(f"Backend schema not found: {schema}")
    SNAPSHOT.write_text(
        json.dumps(extract_model_fields(schema), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {SNAPSHOT}")


if __name__ == "__main__":
    main()
