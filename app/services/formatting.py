"""Jinja2 filters and helpers for presenting values in reports.

Kept separate from templates so the same formatting rules can be reused across
different template styles and languages.

Label-emitting filters (verdicts, bands, yes/no, benchmark names) read from a
per-language dictionary: the renderer builds the filter set with
:func:`build_filters` for the language of the *resolved* template, so a report
never mixes template language and filter-label language. Numbers, currencies,
and units are locale-neutral and shared.
"""
from __future__ import annotations

from typing import Optional

_LABELS = {
    "en": {
        "underpriced": "Underpriced",
        "overpriced": "Overpriced",
        "fairly_priced": "Fairly priced",
        "very_high": "Very high",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "strong": "Strong",
        "average": "Average",
        "weak": "Weak",
        "yes": "Yes",
        "no": "No",
        "benchmark_types": {
            "listing_asking": "Listing asking prices",
            "realized_sale": "Realized sale prices",
            "newbuild_asking": "New-build asking/supply prices",
            "rent_monthly": "Rent CZK/m²/month",
        },
    },
    "sk": {
        "underpriced": "Pod trhovou cenou",
        "overpriced": "Nad trhovou cenou",
        "fairly_priced": "Primeraná cena",
        "very_high": "Veľmi vysoká",
        "high": "Vysoká",
        "medium": "Stredná",
        "low": "Nízka",
        "strong": "Silná",
        "average": "Priemerná",
        "weak": "Slabá",
        "yes": "Áno",
        "no": "Nie",
        "benchmark_types": {
            "listing_asking": "Ponukové ceny inzerátov",
            "realized_sale": "Realizované predajné ceny",
            "newbuild_asking": "Ponukové ceny novostavieb",
            "rent_monthly": "Nájomné za m²/mesiac",
        },
    },
    "cs": {
        "underpriced": "Pod tržní cenou",
        "overpriced": "Nad tržní cenou",
        "fairly_priced": "Přiměřená cena",
        "very_high": "Velmi vysoká",
        "high": "Vysoká",
        "medium": "Střední",
        "low": "Nízká",
        "strong": "Silná",
        "average": "Průměrná",
        "weak": "Slabá",
        "yes": "Ano",
        "no": "Ne",
        "benchmark_types": {
            "listing_asking": "Nabídkové ceny inzerátů",
            "realized_sale": "Realizované prodejní ceny",
            "newbuild_asking": "Nabídkové ceny novostaveb",
            "rent_monthly": "Nájemné za m²/měsíc",
        },
    },
}


def labels_for(language: Optional[str]) -> dict:
    """Labels for ``language``, falling back to English for unknown ones."""
    return _LABELS.get((language or "en").lower(), _LABELS["en"])


# Localized month abbreviations for the date_l10n filter (estima style).
_MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "sk": ["jan", "feb", "mar", "apr", "máj", "jún",
           "júl", "aug", "sep", "okt", "nov", "dec"],
    "cs": ["led", "úno", "bře", "dub", "kvě", "čvn",
           "čvc", "srp", "zář", "říj", "lis", "pro"],
}


_CURRENCY_SYMBOLS = {
    "EUR": "€",
    "USD": "$",
    "GBP": "£",
    "CHF": "CHF ",
    "PLN": "zł",
}


def money(value: Optional[float], currency: str = "EUR") -> str:
    """Format a monetary amount, e.g. ``€ 425,000``."""
    if value is None:
        return "—"
    symbol = _CURRENCY_SYMBOLS.get(currency.upper(), f"{currency} ")
    amount = f"{value:,.0f}"
    # Currencies whose symbol trails the amount (e.g. Polish złoty).
    if currency.upper() == "PLN":
        return f"{amount} {symbol}".strip()
    return f"{symbol}{amount}".strip()


def number(value: Optional[float], decimals: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def area(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f} m²"


def per_sqm(value: Optional[float], currency: str = "EUR") -> str:
    if value is None:
        return "—"
    return f"{money(value, currency)}/m²"


def percent(value: Optional[float]) -> str:
    """Accept either 0..1 or 0..100 and render a whole percentage."""
    if value is None:
        return "—"
    pct = value * 100 if value <= 1 else value
    return f"{pct:.0f}%"


def score_pct(value: Optional[float]) -> Optional[float]:
    """Normalize a 0..1 or 0..100 score to a 0..100 float for progress bars."""
    if value is None:
        return None
    return round(value * 100 if value <= 1 else value, 1)


def distance(value: Optional[float]) -> str:
    if value is None:
        return "—"
    if value < 1:
        return f"{value * 1000:.0f} m"
    return f"{value:.1f} km"


def default(value, fallback: str = "—"):
    return value if value not in (None, "", []) else fallback


def verdict_label(
    list_price: Optional[float],
    estimated_value: Optional[float],
    labels: Optional[dict] = None,
) -> Optional[str]:
    """Classify asking price vs. estimate as underpriced / fairly priced / overpriced.

    A +/-3% band around the estimate is treated as "fairly priced" noise, not a
    meaningful mispricing signal.
    """
    labels = labels or _LABELS["en"]
    if list_price is None or estimated_value is None or list_price == 0:
        return None
    delta_pct = (estimated_value - list_price) / list_price * 100
    if delta_pct > 3:
        return labels["underpriced"]
    if delta_pct < -3:
        return labels["overpriced"]
    return labels["fairly_priced"]


def confidence_label(
    value: Optional[float], labels: Optional[dict] = None
) -> Optional[str]:
    """Map a 0..1 confidence score to low / medium / high."""
    labels = labels or _LABELS["en"]
    if value is None:
        return None
    pct = value * 100 if value <= 1 else value
    if pct >= 75:
        return labels["high"]
    if pct >= 50:
        return labels["medium"]
    return labels["low"]


def similarity_band(value: Optional[float], labels: Optional[dict] = None) -> str:
    """Map a 0..100 similarity score to a coarse band, never a raw '100%'."""
    labels = labels or _LABELS["en"]
    if value is None:
        return "—"
    if value >= 90:
        return labels["very_high"]
    if value >= 75:
        return labels["high"]
    if value >= 50:
        return labels["medium"]
    return labels["low"]


def investor_attractiveness(
    gross_yield: Optional[float], labels: Optional[dict] = None
) -> Optional[str]:
    """Classify gross rental yield as weak / average / strong."""
    labels = labels or _LABELS["en"]
    if gross_yield is None:
        return None
    pct = gross_yield * 100 if gross_yield <= 1 else gross_yield
    if pct >= 6:
        return labels["strong"]
    if pct >= 4:
        return labels["average"]
    return labels["weak"]


def benchmark_type_label(key: Optional[str], labels: Optional[dict] = None) -> str:
    labels = labels or _LABELS["en"]
    if not key:
        return "—"
    return labels["benchmark_types"].get(key, key.replace("_", " ").title())


def walking_time(distance_km: Optional[float]) -> str:
    """Rough walking time estimate at ~5 km/h, for display only."""
    if distance_km is None:
        return "—"
    minutes = round(distance_km / 5 * 60)
    return f"{minutes} min" if minutes >= 1 else "<1 min"


def yesno(value: Optional[bool], labels: Optional[dict] = None) -> str:
    labels = labels or _LABELS["en"]
    if value is None:
        return "—"
    return labels["yes"] if value else labels["no"]


def span_pct(value: Optional[float], lo: Optional[float], hi: Optional[float]) -> Optional[float]:
    """Clamped 0..100 position of ``value`` within [lo, hi], for range strips."""
    if value is None or lo is None or hi is None or hi <= lo:
        return None
    return round(max(0.0, min(1.0, (value - lo) / (hi - lo))) * 100, 1)


def line_chart(
    series,
    subject_value: Optional[float] = None,
    width: int = 660,
    height: int = 200,
) -> Optional[dict]:
    """Compute SVG geometry for a price-trend line chart.

    Accepts a sequence of points with ``period``/``value`` (attributes or dict
    keys); points without a value are skipped. The y-domain is widened to
    include ``subject_value`` so the subject marker always fits on the plot.
    Returns None when fewer than two usable points remain (no chart drawn).
    """
    if not series:
        return None
    pts: list[tuple[str, float]] = []
    for p in series:
        period = p.get("period") if isinstance(p, dict) else getattr(p, "period", None)
        value = p.get("value") if isinstance(p, dict) else getattr(p, "value", None)
        if value is None:
            continue
        pts.append((str(period or ""), float(value)))
    if len(pts) < 2:
        return None

    # Wide right pad so the centered last x-axis label fits inside the viewBox.
    pad_left, pad_right, pad_top, pad_bottom = 52.0, 40.0, 16.0, 26.0
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom

    values = [v for _, v in pts]
    domain = values + ([float(subject_value)] if subject_value is not None else [])
    lo, hi = min(domain), max(domain)
    if hi == lo:  # flat series: give the domain some height
        lo, hi = lo - 1.0, hi + 1.0
    margin = (hi - lo) * 0.08
    lo, hi = lo - margin, hi + margin

    def x_at(i: int) -> float:
        return round(pad_left + plot_w * i / (len(pts) - 1), 1)

    def y_at(v: float) -> float:
        return round(pad_top + plot_h * (1 - (v - lo) / (hi - lo)), 1)

    points = [(x_at(i), y_at(v)) for i, (_, v) in enumerate(pts)]
    points_attr = " ".join(f"{x},{y}" for x, y in points)
    baseline = round(pad_top + plot_h, 1)
    area_attr = f"{points[0][0]},{baseline} {points_attr} {points[-1][0]},{baseline}"

    # At most ~5 x-axis labels, always including the first and last period.
    step = max(1, round((len(pts) - 1) / 4))
    label_indexes = sorted(set(range(0, len(pts), step)) | {len(pts) - 1})
    x_labels = [{"x": points[i][0], "label": pts[i][0]} for i in label_indexes]

    y_ticks = [
        {"y": y_at(lo + (hi - lo) * frac), "label": f"{lo + (hi - lo) * frac:,.0f}"}
        for frac in (0.08, 0.5, 0.92)
    ]

    subject = None
    if subject_value is not None:
        sy = y_at(float(subject_value))
        subject = {
            "x": points[-1][0],
            "y": sy,
            # Keep the label inside the plot even when the dot sits near the top.
            "label_y": max(pad_top + 9.0, sy - 9.0),
            "value": float(subject_value),
        }

    return {
        "width": width,
        "height": height,
        "pad_left": pad_left,
        "pad_top": pad_top,
        "plot_right": round(width - pad_right, 1),
        "baseline": baseline,
        "points": points_attr,
        "area": area_attr,
        "x_labels": x_labels,
        "y_ticks": y_ticks,
        "last": {"x": points[-1][0], "y": points[-1][1], "value": values[-1]},
        "subject": subject,
    }


# --------------------------------------------------------------------------- #
# Estima-style filters (ported from the estima-backend report renderer so both
# products' reports read identically: space-grouped numbers with a trailing
# currency, em-dash fallbacks, localized dates, embedded images, SVG chart).
# --------------------------------------------------------------------------- #

_DASH = "—"
_NNBSP = " "  # narrow no-break space: thousands separator in EU formats

# Cap on remotely fetched images so a rogue URL can't bloat or hang the PDF.
_IMAGE_MAX_BYTES = 6 * 1024 * 1024

_PLACEHOLDER_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' width='400' height='300'>"
    "<rect width='100%' height='100%' fill='#eef1f5'/>"
    "<text x='50%' y='50%' fill='#9aa5b1' font-family='sans-serif' "
    "font-size='18' text-anchor='middle' dominant-baseline='middle'>"
    "Image unavailable</text></svg>"
)


def _placeholder_data_uri() -> str:
    import base64

    return "data:image/svg+xml;base64," + base64.b64encode(
        _PLACEHOLDER_SVG.encode("utf-8")
    ).decode("ascii")


def num(value: Optional[float], decimals: int = 0, suffix: str = "") -> str:
    """Space-grouped number: 3482 -> '3 482', with an optional suffix."""
    if value is None:
        return _DASH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _DASH
    return f"{f:,.{decimals}f}".replace(",", _NNBSP) + suffix


def amount(value: Optional[float], currency: str = "EUR") -> str:
    """Money with trailing currency: 195000 -> '195 000 EUR'."""
    if value is None:
        return _DASH
    try:
        n = round(float(value))
    except (TypeError, ValueError):
        return _DASH
    return f"{n:,}".replace(",", _NNBSP) + f" {currency}"


def signed_amount(value: Optional[float], currency: str = "EUR") -> str:
    if value is None:
        return _DASH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _DASH
    sign = "+" if f > 0 else ("-" if f < 0 else "")
    return f"{sign}{amount(abs(f), currency)}"


def pct(value: Optional[float], decimals: int = 1, signed: bool = False) -> str:
    if value is None:
        return _DASH
    try:
        f = float(value)
    except (TypeError, ValueError):
        return _DASH
    sign = "+" if (signed and f > 0) else ""
    return f"{sign}{f:.{decimals}f} %"


def date_l10n(value, language: str = "en") -> str:
    """Localized 'D Mon YYYY' (e.g. '16 júl 2026' for sk)."""
    if value is None:
        return _DASH
    months = _MONTHS.get((language or "en").lower(), _MONTHS["en"])
    try:
        return f"{value.day} {months[value.month - 1]} {value.year}"
    except (AttributeError, IndexError, TypeError):
        return str(value)


def verdict_key(
    list_price: Optional[float], estimated_value: Optional[float]
) -> str:
    """Language-independent verdict slug for CSS classes and label lookup.

    Same +/-3% band as :func:`verdict_label`; 'unknown' when unassessable.
    """
    if list_price is None or estimated_value is None or list_price == 0:
        return "unknown"
    delta_pct = (estimated_value - list_price) / list_price * 100
    if delta_pct > 3:
        return "undervalued"
    if delta_pct < -3:
        return "overpriced"
    return "fair"


def embed_image(url: Optional[str]) -> str:
    """Return a data URI for ``url``, or a neutral placeholder.

    Fetches go through the same SSRF policy as PDF asset fetching
    (public hosts only, optional allowlist, timeout) and are size-capped.
    Never raises — any failure yields the placeholder, so a broken image URL
    cannot break report generation.
    """
    import base64

    if not url:
        return _placeholder_data_uri()
    if url.startswith("data:"):
        return url
    if not url.startswith(("http://", "https://")):
        return _placeholder_data_uri()

    from app.services import pdf as pdf_service

    try:
        fetched = pdf_service._fetch_remote(url)
        content = fetched["file_obj"].read(_IMAGE_MAX_BYTES + 1)
        if not content or len(content) > _IMAGE_MAX_BYTES:
            return _placeholder_data_uri()
        mime = fetched.get("mime_type") or "image/jpeg"
        if not mime.startswith("image/"):
            mime = "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(content).decode("ascii")
    except Exception:
        return _placeholder_data_uri()


def index_svg(series, width: int = 640, height: int = 150):
    """Render a price-index series as a self-contained SVG line chart.

    Accepts a sequence of points with ``period``/``value`` (attributes or dict
    keys). WeasyPrint ignores CSS inside inline SVG, so every style is an
    attribute. Returns empty markup below 3 usable points.
    """
    from markupsafe import Markup, escape

    pts: list = []
    for p in series or []:
        period = p.get("period") if isinstance(p, dict) else getattr(p, "period", None)
        value = p.get("value") if isinstance(p, dict) else getattr(p, "value", None)
        if value is None:
            continue
        pts.append((str(period or ""), float(value)))
    if len(pts) < 3:
        return Markup("")

    W, H = width, height
    PAD_L, PAD_R, PAD_T, PAD_B = 8, 8, 16, 22
    BRAND, GRID, MUTED = "#123a5e", "#dbe4ec", "#6b7f90"

    vals = [v for _, v in pts]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or max(abs(hi), 1.0)
    lo -= span * 0.10
    hi += span * 0.10
    span = hi - lo

    def x(i: int) -> float:
        return PAD_L + i * (W - PAD_L - PAD_R) / (len(pts) - 1)

    def y(v: float) -> float:
        return PAD_T + (hi - v) * (H - PAD_T - PAD_B) / span

    def fmt(v: float) -> str:
        return f"{v:,.0f}".replace(",", _NNBSP)

    poly = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
    area = f"{PAD_L},{H - PAD_B} {poly} {W - PAD_R},{H - PAD_B}"

    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    for frac in (0.0, 0.5, 1.0):
        gy = PAD_T + frac * (H - PAD_T - PAD_B)
        parts.append(
            f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
    parts.append(f'<polygon points="{area}" fill="{BRAND}" fill-opacity="0.07"/>')
    parts.append(
        f'<polyline points="{poly}" fill="none" stroke="{BRAND}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )
    for i, (_, v) in enumerate(pts):
        r = 3.4 if i == len(pts) - 1 else 2.2
        parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{r}" fill="{BRAND}"/>')
    first_label, first_v = pts[0]
    last_label, last_v = pts[-1]
    parts.append(
        f'<text x="{x(0):.1f}" y="{y(first_v) - 6:.1f}" text-anchor="start" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="9" fill="{MUTED}">'
        f"{fmt(first_v)}</text>"
    )
    parts.append(
        f'<text x="{x(len(pts) - 1):.1f}" y="{y(last_v) - 6:.1f}" text-anchor="end" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="9" font-weight="bold" '
        f'fill="{BRAND}">{fmt(last_v)}</text>'
    )
    for i in (0, len(pts) // 2, len(pts) - 1):
        anchor = "start" if i == 0 else ("end" if i == len(pts) - 1 else "middle")
        parts.append(
            f'<text x="{x(i):.1f}" y="{H - 7}" text-anchor="{anchor}" '
            f'font-family="Helvetica, Arial, sans-serif" font-size="8.5" fill="{MUTED}">'
            f"{escape(pts[i][0])}</text>"
        )
    parts.append("</svg>")
    return Markup("".join(parts))


def wealth_svg(series, buyer_label: str, renter_label: str, width: int = 640, height: int = 180):
    """Two-line buy-vs-rent wealth chart (buyer vs renter net wealth by year).

    Accepts points with ``year``/``buyer``/``renter`` (attributes or dict
    keys). Same constraints as ``index_svg``: attribute-styled SVG (WeasyPrint
    ignores CSS in inline SVG), empty markup below 3 usable points.
    """
    from markupsafe import Markup, escape

    pts: list = []
    for p in series or []:
        get = p.get if isinstance(p, dict) else lambda k, _p=p: getattr(_p, k, None)
        year, buyer, renter = get("year"), get("buyer"), get("renter")
        if year is None or buyer is None or renter is None:
            continue
        pts.append((int(year), float(buyer), float(renter)))
    if len(pts) < 3:
        return Markup("")

    W, H = width, height
    PAD_L, PAD_R, PAD_T, PAD_B = 8, 8, 30, 22
    BUYER, RENTER, GRID, MUTED = "#0e9f6e", "#123a5e", "#dbe4ec", "#6b7f90"

    vals = [v for _, b, r in pts for v in (b, r)]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or max(abs(hi), 1.0)
    lo -= span * 0.08
    hi += span * 0.08
    span = hi - lo

    def x(i: int) -> float:
        return PAD_L + i * (W - PAD_L - PAD_R) / (len(pts) - 1)

    def y(v: float) -> float:
        return PAD_T + (hi - v) * (H - PAD_T - PAD_B) / span

    def fmt(v: float) -> str:
        return f"{v:,.0f}".replace(",", _NNBSP)

    buyer_poly = " ".join(f"{x(i):.1f},{y(b):.1f}" for i, (_, b, _r) in enumerate(pts))
    renter_poly = " ".join(f"{x(i):.1f},{y(r):.1f}" for i, (_, _b, r) in enumerate(pts))

    parts = [
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
        f'xmlns="http://www.w3.org/2000/svg">'
    ]
    for frac in (0.0, 0.5, 1.0):
        gy = PAD_T + frac * (H - PAD_T - PAD_B)
        parts.append(
            f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
    for poly, color in ((renter_poly, RENTER), (buyer_poly, BUYER)):
        parts.append(
            f'<polyline points="{poly}" fill="none" stroke="{color}" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
        )
    # Legend row (top-left), end-value labels, and year ticks.
    lx = float(PAD_L)
    for label, color in ((buyer_label, BUYER), (renter_label, RENTER)):
        parts.append(f'<rect x="{lx:.1f}" y="8" width="8" height="8" rx="1.5" fill="{color}"/>')
        parts.append(
            f'<text x="{lx + 12:.1f}" y="15.5" text-anchor="start" '
            f'font-family="Helvetica, Arial, sans-serif" font-size="9" fill="{MUTED}">'
            f"{escape(label)}</text>"
        )
        lx += 12 + 6.2 * len(label) + 18
    last = pts[-1]
    for v, color in ((last[1], BUYER), (last[2], RENTER)):
        parts.append(
            f'<text x="{x(len(pts) - 1):.1f}" y="{y(v) - 5:.1f}" text-anchor="end" '
            f'font-family="Helvetica, Arial, sans-serif" font-size="9" font-weight="bold" '
            f'fill="{color}">{fmt(v)}</text>'
        )
    for i in (0, len(pts) // 2, len(pts) - 1):
        anchor = "start" if i == 0 else ("end" if i == len(pts) - 1 else "middle")
        parts.append(
            f'<text x="{x(i):.1f}" y="{H - 7}" text-anchor="{anchor}" '
            f'font-family="Helvetica, Arial, sans-serif" font-size="8.5" fill="{MUTED}">'
            f"{pts[i][0]}</text>"
        )
    parts.append("</svg>")
    return Markup("".join(parts))


def build_filters(language: str = "en") -> dict:
    """Jinja2 filter set with label filters bound to ``language``.

    Template usage stays identical across languages (e.g. ``x | yesno``);
    only the emitted label strings differ.
    """
    labels = labels_for(language)
    return {
        "money": money,
        "number": number,
        "area": area,
        "per_sqm": per_sqm,
        "percent": percent,
        "score_pct": score_pct,
        "distance": distance,
        "orblank": default,
        "verdict_label": lambda lp, ev: verdict_label(lp, ev, labels),
        "confidence_label": lambda v: confidence_label(v, labels),
        "similarity_band": lambda v: similarity_band(v, labels),
        "investor_attractiveness": lambda v: investor_attractiveness(v, labels),
        "benchmark_type_label": lambda k: benchmark_type_label(k, labels),
        "walking_time": walking_time,
        "yesno": lambda v: yesno(v, labels),
        "span_pct": span_pct,
        "line_chart": line_chart,
        # estima style (backend-aligned formatting)
        "num": num,
        "amount": amount,
        "signed_amount": signed_amount,
        "pct": pct,
        "dash": default,
        "date_l10n": lambda v: date_l10n(v, language),
        "verdict_key": verdict_key,
        "embed_image": embed_image,
        "index_svg": index_svg,
        "wealth_svg": wealth_svg,
    }


# Default (English) filter set, kept for callers that don't resolve a language.
FILTERS = build_filters("en")
