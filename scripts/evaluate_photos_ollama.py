#!/usr/bin/env python3
"""Enrich an evaluation payload with photo notes from a local Ollama vision model.

Payload-preparation tooling only — this never runs inside the service. It reads
a payload JSON, sends each listing photo (vision_analysis.image_metrics[].url)
to a local Ollama model, and writes back:

  * a per-photo Slovak `note` (room type, visible condition, staging detection)
  * a `condition_assessment` block (element/state/note items + summary)

Everything produced is descriptive text for the report; no scores and nothing
that feeds valuation. Stdlib only — no new dependencies.

Usage:
    python scripts/evaluate_photos_ollama.py samples/sample_kosice_odborarska.json
    # options: --model gemma3:27b  --ollama-url http://localhost:11434
    #          --out PATH (default: <input>.ollama.json)  --in-place
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import socket
import sys
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) estima-photo-eval"

# Photo URLs come from scraped listing payloads, i.e. semi-untrusted input.
# Mirror the SSRF policy of app/services/pdf.py (public hosts only, redirects
# re-validated) without importing app/ — this script must stay standalone.
MAX_IMAGE_BYTES = 25 * 1024 * 1024


class PhotoFetchBlockedError(Exception):
    """A photo URL was rejected by the fetch policy."""


def _validate_photo_url(url: str) -> None:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise PhotoFetchBlockedError(f"blocked URL scheme {scheme!r}")
    host = (parts.hostname or "").lower()
    if not host:
        raise PhotoFetchBlockedError("blocked URL without host")
    port = parts.port or (443 if scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise PhotoFetchBlockedError(f"cannot resolve host: {host}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise PhotoFetchBlockedError(
                f"blocked host resolving to non-public address: {host}"
            )


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-apply the photo-URL policy on every redirect hop."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_photo_url(urljoin(req.full_url, newurl))
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_photo_opener = urllib.request.build_opener(_ValidatedRedirectHandler)

NOTE_SCHEMA = {
    "type": "object",
    "properties": {"note": {"type": "string"}},
    "required": ["note"],
}

CONDITION_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "element": {"type": "string"},
                    "state": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["element", "state", "note"],
            },
        },
        "summary": {"type": "string"},
        "overall_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "overall_label": {"type": "string"},
    },
    "required": ["items", "summary", "overall_score", "overall_label"],
}

NOTE_PROMPT = (
    "Si asistent realitnej kancelárie. Na fotografii je záber z inzerátu.\n"
    "{context}"
    "Napíš JEDNU krátku vecnú poznámku po slovensky (max. 25 slov) v tvare: "
    "typ miestnosti/záberu — čo vidno a v akom stave. "
    "Ak zariadenie pôsobí ako počítačová vizualizácia alebo virtuálny home staging, uveď to. "
    "Kontext inzerátu využi na presnejšie pomenovanie miestnosti, ale opisuj len to, "
    "čo je na fotografii skutočne viditeľné. "
    "Žiadne hodnotenie ceny, žiadne odhady."
)

CONDITION_PROMPT = (
    "Si asistent realitnej kancelárie. Nižšie sú poznámky k jednotlivým fotografiám "
    "z inzerátu jednej nehnuteľnosti. Zostav orientačné vyhodnotenie stavu "
    "nehnuteľnosti po slovensky.\n"
    "{context}\n"
    "Vráť JSON s poľom `items` (prvky ako Podlahy, Steny a stropy, Kuchyňa, "
    "Kúpeľňa a WC, Okná, Vykurovanie, Vstupné dvere — iba tie, ku ktorým fotografie "
    "niečo hovoria) — každý s `element`, `state` (stručný stav, napr. 'Nové', "
    "'Po rekonštrukcii', 'Nejednoznačné z fotografií') a `note` (jedna veta, čo vidno). "
    "A `summary`: 2–3 vety o celkovom stave. Ak je časť záberov pravdepodobne "
    "vizualizácia, výslovne odporuč overenie na obhliadke. "
    "Ďalej `overall_score`: celkové skóre stavu a rekonštrukcie 0–100 "
    "(100 = kompletná nová rekonštrukcia, 50 = čiastočne renovované/pôvodný "
    "udržiavaný stav, 0 = v dezolátnom stave) — hodnotí stav nehnuteľnosti, "
    "nie kvalitu fotografií. A `overall_label`: krátky slovný stav "
    "(napr. 'Po kompletnej rekonštrukcii', 'Čiastočne renovovaný', 'Pôvodný stav'). "
    "Iba viditeľné skutočnosti — žiadne ceny ani odhady hodnoty.\n\n"
    "Poznámky k fotografiám:\n{notes}"
)


def listing_context(data: dict[str, Any], extra: str | None) -> str:
    """Compact Slovak context block from the payload's property facts.

    Grounds room naming (layout, area) without inviting the model to describe
    anything not visible in the photo itself.
    """
    prop = data.get("property") or {}
    facts: list[str] = []
    if prop.get("title"):
        facts.append(str(prop["title"]))
    for key, label in (
        ("layout", "dispozícia"),
        ("rooms", "počet izieb"),
        ("floor_area", "výmera v m²"),
        ("locality", "lokalita"),
        ("city", "mesto"),
    ):
        if prop.get(key) is not None:
            facts.append(f"{label}: {prop[key]}")
    if extra:
        facts.append(f"popis z inzerátu: {extra.strip()}")
    if not facts:
        return ""
    return "Kontext inzerátu: " + "; ".join(facts) + ".\n"


def http_json(url: str, body: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_image_b64(url: str, timeout: int = 30) -> str:
    _validate_photo_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with _photo_opener.open(req, timeout=timeout) as resp:
        data = resp.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise PhotoFetchBlockedError(
                f"image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB cap"
            )
        return base64.b64encode(data).decode("ascii")


def ollama_chat(
    ollama_url: str,
    model: str,
    prompt: str,
    schema: dict[str, Any],
    images: list[str] | None = None,
    timeout: int = 600,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "user", "content": prompt}
    if images:
        message["images"] = images
    body = {
        "model": model,
        "messages": [message],
        "stream": False,
        "format": schema,
        "options": {"temperature": 0.2},
    }
    resp = http_json(f"{ollama_url}/api/chat", body, timeout)
    return json.loads(resp["message"]["content"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument(
        "--context",
        default=None,
        help="free-text listing description to ground the notes (optional)",
    )
    args = parser.parse_args()

    data = json.loads(args.payload.read_text(encoding="utf-8"))
    context = listing_context(data, args.context)
    metrics = (data.get("vision_analysis") or {}).get("image_metrics") or []
    if not metrics:
        print("payload has no vision_analysis.image_metrics — nothing to evaluate")
        return 1

    notes: list[str] = []
    for i, entry in enumerate(metrics, start=1):
        url = entry.get("url")
        if not url:
            continue
        print(f"[{i}/{len(metrics)}] {url}")
        try:
            image = fetch_image_b64(url)
        except Exception as exc:  # noqa: BLE001 — photo hosts rot; skip and continue
            print(f"    fetch failed, keeping existing note: {exc}")
            continue
        result = ollama_chat(
            args.ollama_url,
            args.model,
            NOTE_PROMPT.format(context=context),
            NOTE_SCHEMA,
            images=[image],
        )
        note = result["note"].strip()
        entry["note"] = note
        notes.append(f"Foto {i}: {note}")
        print(f"    {note}")

    if notes:
        print("assembling condition assessment …")
        cond = ollama_chat(
            args.ollama_url,
            args.model,
            CONDITION_PROMPT.format(context=context, notes="\n".join(notes)),
            CONDITION_SCHEMA,
        )
        data["condition_assessment"] = {
            "available": True,
            "source": f"Orientačné vyhodnotenie z fotografií inzerátu (Ollama {args.model})",
            "items": cond["items"],
            "summary": cond["summary"].strip(),
            "overall_score": max(0, min(100, int(cond["overall_score"]))),
            "overall_label": cond["overall_label"].strip(),
        }

    out = args.payload if args.in_place else (
        args.out or args.payload.with_suffix(".ollama.json")
    )
    out.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
