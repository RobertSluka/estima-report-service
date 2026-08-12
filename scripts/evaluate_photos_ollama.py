#!/usr/bin/env python3
"""Enrich an evaluation payload with photo notes from a local Ollama vision model.

Payload-preparation tooling only — this never runs inside the service. It reads
a payload JSON, sends each listing photo (vision_analysis.image_metrics[].url)
to a local Ollama model, and writes back:

  * a per-photo `note` (room type, visible condition, staging detection)
  * a `condition_assessment` block (element/state/note items + summary)

Both are written in the language selected with --lang (sk default, cs) — it
must match the report the enrichment lands in.

Everything produced is descriptive text for the report; no scores and nothing
that feeds valuation. Stdlib only — no new dependencies.

Usage:
    python scripts/evaluate_photos_ollama.py payload.json [more.json ...]
    # options: --model gemma3:27b  --ollama-url http://localhost:11434
    #          --out PATH (single payload only; default: <input>.ollama.json)
    #          --in-place  --lang sk|cs  --context "listing text"
    #          --condition-only (rebuild assessment from existing notes)
    # batch: pass several payloads (e.g. payloads/*.json) — one .ollama.json each
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

# Structured per-photo extraction. The scoring stage never sees the photos,
# only what this schema captures — a bare prose note drops exactly the
# element-level evidence (radiators, door jambs, water hookups) that the
# condition table and renovation score need, so extraction must be itemized.
_ELEMENT_KEYS = ("floors", "walls", "windows", "heating", "doors")
NOTE_SCHEMA = {
    "type": "object",
    "properties": {
        "room": {"type": "string"},
        "elements": {
            "type": "object",
            "properties": {k: {"type": ["string", "null"]} for k in _ELEMENT_KEYS},
            "required": list(_ELEMENT_KEYS),
        },
        "features": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "staging_signs": {"type": ["string", "null"]},
        "note": {"type": "string"},
    },
    "required": ["room", "elements", "features", "staging_signs", "note"],
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
        "score_positives": {"type": "array", "items": {"type": "string"}},
        "score_negatives": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "items", "summary", "overall_score", "overall_label",
        "score_positives", "score_negatives",
    ],
}

# Per-language prompt/string packs. The language must match the report the
# enrichment lands in (sk for estima.sk, cs for estimacz.cz) — the template
# renders these strings verbatim.
LANGS: dict[str, dict[str, Any]] = {
    "sk": {
        "note_prompt": (
            "Si asistent realitnej kancelárie a analyzuješ fotografiu z inzerátu.\n"
            "{context}"
            "Vráť JSON po slovensky:\n"
            "- `room`: typ miestnosti/záberu. Rešpektuj dispozíciu z kontextu — "
            "kuchynský kút bez linky spoznáš podľa prívodu vody a zásuviek v pracovnej "
            "výške; chodbu podľa vstupných dverí alebo viacerých dverných otvorov.\n"
            "- `elements`: stav LEN toho, čo na fotografii jasne vidno, inak null: "
            "`floors` (typ a stav podlahy), `walls` (povrch, nedokončené miesta), "
            "`windows` (materiál/typ), `heating` (typ radiátora — nový panelový vs. "
            "staré rebrové teleso), `doors` (interiérové/vstupné; chýbajúce dvere a "
            "surové zárubne VŽDY uveď).\n"
            "- `features`: 0–3 detaily užitočné pre kupujúceho (bezpečnostné dvere, "
            "prívod vody, nová elektroinštalácia/istič, klimatizácia a pod.).\n"
            "- `staging_signs`: konkrétne znaky počítačového renderu (nereálne tiene, "
            "dokonale hladké textúry, nábytok nesediaci s perspektívou), inak null — "
            "moderné zariadenie samo osebe nie je staging.\n"
            "- `note`: JEDNA vecná veta (max. 30 slov) zložená z vyššie uvedeného: "
            "miestnosť — čo vidno a v akom stave. ZAKÁZANÉ sú subjektívne prívlastky "
            "(priestranný, vkusný, pekný, útulný, moderný bez opory) a akékoľvek "
            "hodnotenie ceny."
        ),
        "condition_prompt": (
            "Si asistent realitnej kancelárie. Nižšie sú štruktúrované pozorovania "
            "z jednotlivých fotografií inzerátu jednej nehnuteľnosti (miestnosť, stav "
            "prvkov, detaily). Zostav orientačné vyhodnotenie stavu nehnuteľnosti "
            "po slovensky.\n"
            "{context}\n"
            "Počet obytných izieb je daný dispozíciou z kontextu — ak sa rovnaký typ "
            "miestnosti opakuje vo viacerých záberoch, sú to tie isté miestnosti "
            "z rôznych uhlov, nie ďalšie izby. Stav prvkov (podlahy, okná, kúrenie, "
            "dvere) odvoď prednostne z polí `elements`, nie z voľného textu.\n"
            "Vráť JSON s poľom `items` (prvky ako Podlahy, Steny a stropy, Kuchyňa, "
            "Kúpeľňa a WC, Okná, Vykurovanie, Vstupné dvere — iba tie, ku ktorým fotografie "
            "niečo hovoria) — každý s `element`, `state` (stručný stav, napr. 'Nové', "
            "'Po rekonštrukcii', 'Nejednoznačné z fotografií') a `note` (jedna veta, čo vidno). "
            "A `summary`: 2–3 vety o celkovom stave. Ak je časť záberov pravdepodobne "
            "vizualizácia, výslovne odporuč overenie na obhliadke. Pozor: ak sa tá istá "
            "miestnosť objavuje v poznámkach prázdna aj zariadená, zariadené zábery sú "
            "pravdepodobne virtuálny home staging — zohľadni to v hodnotení aj v summary. "
            "Ďalej `overall_score`: celkové skóre stavu a rekonštrukcie 0–100 "
            "(100 = kompletná nová rekonštrukcia, 50 = čiastočne renovované/pôvodný "
            "udržiavaný stav, 0 = v dezolátnom stave) — hodnotí stav nehnuteľnosti, "
            "nie kvalitu fotografií. A `overall_label`: krátky slovný stav "
            "(napr. 'Po kompletnej rekonštrukcii', 'Čiastočne renovovaný', 'Pôvodný stav'). "
            "K skóre pridaj zdôvodnenie: `score_positives` — 2 až 4 krátke body (max. 8 slov), "
            "čo skóre zvyšuje, a `score_negatives` — 2 až 4 krátke body, čo ho znižuje "
            "alebo znejasňuje (vrátane neistoty z vizualizácií). Každý bod musí vychádzať "
            "z poznámok k fotografiám, nie z domnienok. "
            "Iba viditeľné skutočnosti — žiadne ceny ani odhady hodnoty.\n\n"
            "Poznámky k fotografiám:\n{notes}"
        ),
        "context_head": "Kontext inzerátu: ",
        "context_desc": "popis z inzerátu",
        "fact_labels": (
            ("layout", "dispozícia"),
            ("rooms", "počet izieb"),
            ("floor_area", "výmera v m²"),
            ("locality", "lokalita"),
            ("city", "mesto"),
        ),
        "photo_word": "Foto",
        "source": "Orientačné vyhodnotenie z fotografií inzerátu (Ollama {model})",
    },
    "cs": {
        "note_prompt": (
            "Jsi asistent realitní kanceláře a analyzuješ fotografii z inzerátu.\n"
            "{context}"
            "Vrať JSON česky:\n"
            "- `room`: typ místnosti/záběru. Respektuj dispozici z kontextu — "
            "kuchyňský kout bez linky poznáš podle přívodu vody a zásuvek v pracovní "
            "výšce; chodbu podle vstupních dveří nebo více dveřních otvorů.\n"
            "- `elements`: stav JEN toho, co je na fotografii jasně vidět, jinak null: "
            "`floors` (typ a stav podlahy), `walls` (povrch, nedokončená místa), "
            "`windows` (materiál/typ), `heating` (typ radiátoru — nový panelový vs. "
            "staré žebrové těleso), `doors` (interiérové/vstupní; chybějící dveře a "
            "surové zárubně VŽDY uveď).\n"
            "- `features`: 0–3 detaily užitečné pro kupujícího (bezpečnostní dveře, "
            "přívod vody, nová elektroinstalace/jistič, klimatizace apod.).\n"
            "- `staging_signs`: konkrétní známky počítačového renderu (nereálné stíny, "
            "dokonale hladké textury, nábytek nesedící s perspektivou), jinak null — "
            "moderní zařízení samo o sobě staging není.\n"
            "- `note`: JEDNA věcná věta (max. 30 slov) složená z výše uvedeného: "
            "místnost — co je vidět a v jakém stavu. ZAKÁZANÁ jsou subjektivní přídavná "
            "jména (prostorný, vkusný, pěkný, útulný, moderní bez opory) a jakékoli "
            "hodnocení ceny."
        ),
        "condition_prompt": (
            "Jsi asistent realitní kanceláře. Níže jsou strukturovaná pozorování "
            "z jednotlivých fotografií inzerátu jedné nemovitosti (místnost, stav "
            "prvků, detaily). Sestav orientační vyhodnocení stavu nemovitosti "
            "česky.\n"
            "{context}\n"
            "Počet obytných pokojů je dán dispozicí z kontextu — pokud se stejný typ "
            "místnosti opakuje na více záběrech, jde o tytéž místnosti z různých úhlů, "
            "ne o další pokoje. Stav prvků (podlahy, okna, vytápění, dveře) odvoď "
            "přednostně z polí `elements`, ne z volného textu.\n"
            "Vrať JSON s polem `items` (prvky jako Podlahy, Stěny a stropy, Kuchyň, "
            "Koupelna a WC, Okna, Vytápění, Vstupní dveře — jen ty, ke kterým fotografie "
            "něco říkají) — každý s `element`, `state` (stručný stav, např. 'Nové', "
            "'Po rekonstrukci', 'Nejednoznačné z fotografií') a `note` (jedna věta, co je vidět). "
            "A `summary`: 2–3 věty o celkovém stavu. Pokud je část záběrů pravděpodobně "
            "vizualizace, výslovně doporuč ověření na prohlídce. Pozor: pokud se tatáž "
            "místnost objevuje v poznámkách prázdná i zařízená, zařízené záběry jsou "
            "pravděpodobně virtuální home staging — zohledni to v hodnocení i v summary. "
            "Dále `overall_score`: celkové skóre stavu a rekonstrukce 0–100 "
            "(100 = kompletní nová rekonstrukce, 50 = částečně renovované/původní "
            "udržovaný stav, 0 = v dezolátním stavu) — hodnotí stav nemovitosti, "
            "ne kvalitu fotografií. A `overall_label`: krátký slovní stav "
            "(např. 'Po kompletní rekonstrukci', 'Částečně renovovaný', 'Původní stav'). "
            "Ke skóre přidej zdůvodnění: `score_positives` — 2 až 4 krátké body (max. 8 slov), "
            "co skóre zvyšuje, a `score_negatives` — 2 až 4 krátké body, co ho snižuje "
            "nebo znejasňuje (včetně nejistoty z vizualizací). Každý bod musí vycházet "
            "z poznámek k fotografiím, ne z domněnek. "
            "Jen viditelné skutečnosti — žádné ceny ani odhady hodnoty.\n\n"
            "Poznámky k fotografiím:\n{notes}"
        ),
        "context_head": "Kontext inzerátu: ",
        "context_desc": "popis z inzerátu",
        "fact_labels": (
            ("layout", "dispozice"),
            ("rooms", "počet pokojů"),
            ("floor_area", "výměra v m²"),
            ("locality", "lokalita"),
            ("city", "město"),
        ),
        "photo_word": "Foto",
        "source": "Orientační vyhodnocení z fotografií inzerátu (Ollama {model})",
    },
}


def listing_context(data: dict[str, Any], extra: str | None, L: dict[str, Any]) -> str:
    """Compact context block from the payload's property facts, in the
    enrichment language.

    Grounds room naming (layout, area) without inviting the model to describe
    anything not visible in the photo itself.
    """
    prop = data.get("property") or {}
    facts: list[str] = []
    if prop.get("title"):
        facts.append(str(prop["title"]))
    for key, label in L["fact_labels"]:
        if prop.get(key) is not None:
            facts.append(f"{label}: {prop[key]}")
    if extra:
        facts.append(f"{L['context_desc']}: {extra.strip()}")
    if not facts:
        return ""
    return L["context_head"] + "; ".join(facts) + ".\n"


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
        # Deterministic decoding: identical payload -> identical notes/score
        # (0.2 gave a ±5 score drift across otherwise identical runs).
        "options": {"temperature": 0, "seed": 7},
    }
    resp = http_json(f"{ollama_url}/api/chat", body, timeout)
    return json.loads(resp["message"]["content"])


def evidence_line(photo_word: str, index: int, r: dict[str, Any]) -> str:
    """One assembly-input line from a structured per-photo extraction.

    Element states go to the scorer verbatim — the prose note alone would
    re-drop the details the structured pass exists to keep.
    """
    parts = [f"{photo_word} {index} — {r.get('room', '?')}"]
    for key in _ELEMENT_KEYS:
        value = (r.get("elements") or {}).get(key)
        if value:
            parts.append(f"{key}: {value}")
    if r.get("features"):
        parts.append("detaily: " + ", ".join(r["features"]))
    if r.get("staging_signs"):
        parts.append(f"staging: {r['staging_signs']}")
    parts.append(f"poznámka: {r.get('note', '')}")
    return "; ".join(parts)


def enrich_payload(payload_path: Path, args: argparse.Namespace, L: dict[str, Any]) -> bool:
    """Run the full enrichment for one payload file; returns success."""
    data = json.loads(payload_path.read_text(encoding="utf-8"))
    # Listing description grounds the notes; explicit --context wins, else the
    # payload's own description (capped so the prompt stays photo-centric).
    extra = args.context or ((data.get("property") or {}).get("description") or "")[:600]
    context = listing_context(data, extra or None, L)
    metrics = (data.get("vision_analysis") or {}).get("image_metrics") or []
    if not metrics:
        print(f"{payload_path}: no vision_analysis.image_metrics — nothing to evaluate")
        return False

    notes: list[str] = []
    if args.condition_only:
        notes = [
            f"{L['photo_word']} {i}: {entry['note']}"
            for i, entry in enumerate(metrics, start=1)
            if entry.get("note")
        ]
        if not notes:
            print("--condition-only needs existing per-photo notes in the payload")
            return False
    else:
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
                L["note_prompt"].format(context=context),
                NOTE_SCHEMA,
                images=[image],
            )
            note = result["note"].strip()
            entry["note"] = note
            notes.append(evidence_line(L["photo_word"], i, result))
            print(f"    [{result.get('room', '?')}] {note}")

    if notes:
        print("assembling condition assessment …")
        cond = ollama_chat(
            args.ollama_url,
            args.model,
            L["condition_prompt"].format(context=context, notes="\n".join(notes)),
            CONDITION_SCHEMA,
        )
        data["condition_assessment"] = {
            "available": True,
            "source": L["source"].format(model=args.model),
            "items": cond["items"],
            "summary": cond["summary"].strip(),
            "overall_score": max(0, min(100, int(cond["overall_score"]))),
            "overall_label": cond["overall_label"].strip(),
            "score_positives": [s.strip() for s in cond["score_positives"] if s.strip()],
            "score_negatives": [s.strip() for s in cond["score_negatives"] if s.strip()],
        }

    out = payload_path if args.in_place else (
        args.out or payload_path.with_suffix(".ollama.json")
    )
    out.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"written: {out}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "payloads",
        type=Path,
        nargs="+",
        help="one or more payload JSON files (batch runs write one "
        "<input>.ollama.json each)",
    )
    parser.add_argument("--model", default="gemma3:27b")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument(
        "--context",
        default=None,
        help="free-text listing description to ground the notes "
        "(default: the payload's property.description when present)",
    )
    parser.add_argument(
        "--lang",
        choices=sorted(LANGS),
        default="sk",
        help="language of notes/assessment — must match the target report (default: sk)",
    )
    parser.add_argument(
        "--condition-only",
        action="store_true",
        help="skip per-photo evaluation; rebuild the condition assessment "
        "from the notes already present in the payload (one model call)",
    )
    args = parser.parse_args()
    L = LANGS[args.lang]
    if args.out and len(args.payloads) > 1:
        parser.error("--out only makes sense with a single payload")

    ok = True
    for n, payload_path in enumerate(args.payloads, start=1):
        if len(args.payloads) > 1:
            print(f"=== [{n}/{len(args.payloads)}] {payload_path} ===")
        ok = enrich_payload(payload_path, args, L) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
