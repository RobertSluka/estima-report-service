"""Architecture guardrails: the CLAUDE.md design rules, as executable tests.

Every rule here mirrors a written constraint of this repo. If one of these
fails, the fix is almost never to edit the test — it is to respect the rule,
or to change the rule deliberately (update CLAUDE.md and the test together).
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
PDF_MODULE = APP_DIR / "services" / "pdf.py"
CONFIG_MODULE = APP_DIR / "config.py"
REQUIREMENTS = ROOT / "requirements.txt"
TEMPLATES_DIR = APP_DIR / "templates"
OPENAPI_SNAPSHOT = ROOT / "tests" / "openapi_snapshot.json"

# Never change one of this pair without the other (mismatch crashes with
# "'super' object has no attribute 'transform'").
PINNED_PAIR = {"weasyprint": "62.3", "pydyf": "0.10.0"}


def _python_files():
    return sorted(APP_DIR.rglob("*.py"))


def _imports_of(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node, alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node, node.module


def test_weasyprint_only_imported_in_pdf_module():
    """CLAUDE.md: 'Import WeasyPrint outside app/services/pdf.py' is forbidden."""
    offenders = []
    for path in _python_files():
        if path == PDF_MODULE:
            continue
        for node, module in _imports_of(path):
            if module.split(".")[0] == "weasyprint":
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, (
        "WeasyPrint imported outside app/services/pdf.py (the isolation layer "
        f"that keeps it swappable): {offenders}"
    )


def test_env_access_only_in_config():
    """CLAUDE.md: config only via app.config.settings — never os.getenv elsewhere."""
    offenders = []
    for path in _python_files():
        if path == CONFIG_MODULE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr in ("getenv", "environ")
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module == "os":
                if any(a.name in ("getenv", "environ") for a in node.names):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, (
        f"Environment read outside app/config.py: {offenders} — add a Settings "
        "field instead."
    )


def test_requirements_are_fully_pinned():
    """CLAUDE.md: pinned dependencies (pkg==x.y.z); no unpinned/loose specs."""
    pins = {}
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9._-]+)(\[[A-Za-z0-9,._-]+\])?==(\S+)", line)
        assert match, f"Unpinned or malformed requirement: {line!r}"
        pins[match.group(1).lower()] = match.group(3)

    for package, version in PINNED_PAIR.items():
        assert pins.get(package) == version, (
            f"{package} must stay pinned to {version} — weasyprint/pydyf are a "
            "matched pair; change both deliberately (and update this test + "
            "CLAUDE.md) or neither."
        )


def test_every_template_language_dir_has_report_html():
    """Template contract: templates/<style>/<language>/report.html."""
    styles = [d for d in TEMPLATES_DIR.iterdir() if d.is_dir()]
    assert styles, "no template styles found"
    for style in styles:
        language_dirs = [d for d in style.iterdir() if d.is_dir()]
        assert language_dirs, f"style '{style.name}' has no language dirs"
        for language_dir in language_dirs:
            assert (language_dir / "report.html").is_file(), (
                f"templates/{style.name}/{language_dir.name}/ lacks report.html — "
                "the renderer resolves exactly that filename"
            )
    # The final fallback of the resolution chain must always exist.
    assert (TEMPLATES_DIR / "default" / "en" / "report.html").is_file()


def test_public_api_surface_matches_snapshot():
    """CLAUDE.md: the public API surface is frozen; other services consume it.

    On an intentional change: python scripts/update_openapi_snapshot.py and
    commit the snapshot diff (plus a CLAUDE.md/README update) in the same PR.
    """
    import importlib.util

    from app.main import app

    spec = importlib.util.spec_from_file_location(
        "update_openapi_snapshot", ROOT / "scripts" / "update_openapi_snapshot.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    actual = module.api_surface(app.openapi())
    expected = json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))
    assert actual == expected, (
        "Public API surface changed. If intentional, run "
        "'python scripts/update_openapi_snapshot.py' and commit the diff."
    )
