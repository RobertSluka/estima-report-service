"""Runtime configuration.

All values can be overridden with environment variables so the service behaves
the same locally, in Docker, and (later) in a deployed environment.
"""
from __future__ import annotations

import os
from pathlib import Path

# Repository root (…/estima-report-service)
BASE_DIR = Path(__file__).resolve().parent.parent


def _path_env(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


class Settings:
    """Service settings resolved from the environment."""

    # Where generated HTML/PDF artifacts are written.
    REPORTS_DIR: Path = _path_env("REPORTS_DIR", BASE_DIR / "reports")

    # Where Jinja2 templates live. Each subdirectory is one report "style".
    TEMPLATES_DIR: Path = _path_env("TEMPLATES_DIR", BASE_DIR / "app" / "templates")

    # Static assets (fonts, logos) that templates may reference.
    ASSETS_DIR: Path = _path_env("ASSETS_DIR", BASE_DIR / "app" / "assets")

    # Frontend UI static files (index.html served at "/").
    STATIC_DIR: Path = _path_env("STATIC_DIR", BASE_DIR / "app" / "static")

    # Bundled demo payload, exposed to the UI via GET /sample.
    SAMPLE_PATH: Path = _path_env(
        "SAMPLE_PATH", BASE_DIR / "samples" / "sample_evaluation.json"
    )

    # Default template style + language when the payload does not specify one.
    DEFAULT_TEMPLATE: str = os.getenv("DEFAULT_TEMPLATE", "default")
    DEFAULT_LANGUAGE: str = os.getenv("DEFAULT_LANGUAGE", "en")

    # Public base URL used when building preview/download links in responses.
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

    def ensure_dirs(self) -> None:
        self.REPORTS_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
