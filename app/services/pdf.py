"""HTML → PDF conversion.

WeasyPrint is used because it renders print-oriented CSS well and runs headless
in a container without a browser engine. The conversion is isolated behind this
module so it can later be swapped for Playwright/Puppeteer without touching the
rest of the service.

Asset fetching during conversion is restricted (see ``_restricted_url_fetcher``):
payloads carry arbitrary URLs (listing images, agency logos, map tiles), and
WeasyPrint would otherwise fetch them server-side with no timeout — an SSRF
surface and a way for one slow remote host to stall report generation.
Policy: ``data:`` URIs pass through, ``file:`` only under ``ASSETS_DIR``,
``http(s)`` only to hosts resolving to public addresses (optionally further
narrowed via ``ASSET_ALLOWED_HOSTS``), with ``ASSET_FETCH_TIMEOUT`` applied
and redirects re-validated.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname


class AssetFetchBlockedError(ValueError):
    """Raised when a report asset URL violates the fetch policy."""


def _validate_file_url(url: str) -> None:
    """Allow ``file:`` access only inside the configured assets directory."""
    from app.config import settings

    path = Path(url2pathname(urlsplit(url).path)).resolve()
    assets = settings.ASSETS_DIR.resolve()
    if assets != path and assets not in path.parents:
        raise AssetFetchBlockedError(
            f"Blocked local file outside assets dir: {url[:200]}"
        )


def _validate_remote_url(url: str) -> None:
    """Reject remote asset hosts that are disallowed or non-public.

    DNS is resolved here for validation; the subsequent fetch re-resolves
    (an accepted TOCTOU trade-off for a rendering service on a private
    network — the allowlist closes it completely when configured).
    """
    from app.config import settings

    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        raise AssetFetchBlockedError(f"Blocked asset URL without host: {url[:200]}")

    allowed = settings.ASSET_ALLOWED_HOSTS
    if allowed and not any(host == h or host.endswith("." + h) for h in allowed):
        raise AssetFetchBlockedError(
            f"Blocked asset host not in ASSET_ALLOWED_HOSTS: {host}"
        )

    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise AssetFetchBlockedError(f"Cannot resolve asset host: {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise AssetFetchBlockedError(
                f"Blocked asset host resolving to non-public address: {host}"
            )


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-apply the remote-host policy on every redirect hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_remote_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _fetch_remote(url: str) -> dict:
    from app.config import settings

    _validate_remote_url(url)
    opener = urllib.request.build_opener(_ValidatedRedirectHandler)
    response = opener.open(url, timeout=settings.ASSET_FETCH_TIMEOUT)
    return {
        "file_obj": response,
        "mime_type": response.headers.get_content_type(),
        "encoding": response.headers.get_content_charset(),
        "redirected_url": response.geturl(),
    }


def _restricted_url_fetcher(url: str, timeout: float = 10, ssl_context=None) -> dict:
    scheme = urlsplit(url).scheme.lower()
    if scheme in ("http", "https"):
        return _fetch_remote(url)
    if scheme in ("data", "file"):
        if scheme == "file":
            _validate_file_url(url)
        from weasyprint import default_url_fetcher

        return default_url_fetcher(url)
    raise AssetFetchBlockedError(
        f"Blocked asset URL scheme {scheme!r}: {url[:200]}"
    )


def html_to_pdf(html: str, output_path: Path, base_url: str) -> Path:
    """Render ``html`` to a PDF file at ``output_path``.

    ``base_url`` lets WeasyPrint resolve relative asset references (fonts,
    local images) contained in the HTML/CSS.
    """
    # Imported lazily so importing the package (e.g. for tests that only render
    # HTML) does not require WeasyPrint's native dependencies to be installed.
    from weasyprint import HTML

    output_path.parent.mkdir(parents=True, exist_ok=True)
    HTML(
        string=html, base_url=base_url, url_fetcher=_restricted_url_fetcher
    ).write_pdf(str(output_path))
    return output_path
