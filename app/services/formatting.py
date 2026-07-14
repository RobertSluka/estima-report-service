"""Jinja2 filters and helpers for presenting values in reports.

Kept separate from templates so the same formatting rules can be reused across
different template styles and languages.
"""
from __future__ import annotations

from typing import Optional

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


def verdict_label(list_price: Optional[float], estimated_value: Optional[float]) -> Optional[str]:
    """Classify asking price vs. estimate as underpriced / fairly priced / overpriced.

    A +/-3% band around the estimate is treated as "fairly priced" noise, not a
    meaningful mispricing signal.
    """
    if list_price is None or estimated_value is None or list_price == 0:
        return None
    delta_pct = (estimated_value - list_price) / list_price * 100
    if delta_pct > 3:
        return "Underpriced"
    if delta_pct < -3:
        return "Overpriced"
    return "Fairly priced"


def confidence_label(value: Optional[float]) -> Optional[str]:
    """Map a 0..1 confidence score to low / medium / high."""
    if value is None:
        return None
    pct = value * 100 if value <= 1 else value
    if pct >= 75:
        return "High"
    if pct >= 50:
        return "Medium"
    return "Low"


def similarity_band(value: Optional[float]) -> str:
    """Map a 0..100 similarity score to a coarse band, never a raw '100%'."""
    if value is None:
        return "—"
    if value >= 90:
        return "Very high"
    if value >= 75:
        return "High"
    if value >= 50:
        return "Medium"
    return "Low"


def investor_attractiveness(gross_yield: Optional[float]) -> Optional[str]:
    """Classify gross rental yield as weak / average / strong."""
    if gross_yield is None:
        return None
    pct = gross_yield * 100 if gross_yield <= 1 else gross_yield
    if pct >= 6:
        return "Strong"
    if pct >= 4:
        return "Average"
    return "Weak"


_BENCHMARK_TYPE_LABELS = {
    "listing_asking": "Listing asking prices",
    "realized_sale": "Realized sale prices",
    "newbuild_asking": "New-build asking/supply prices",
    "rent_monthly": "Rent CZK/m²/month",
}


def benchmark_type_label(key: Optional[str]) -> str:
    if not key:
        return "—"
    return _BENCHMARK_TYPE_LABELS.get(key, key.replace("_", " ").title())


def walking_time(distance_km: Optional[float]) -> str:
    """Rough walking time estimate at ~5 km/h, for display only."""
    if distance_km is None:
        return "—"
    minutes = round(distance_km / 5 * 60)
    return f"{minutes} min" if minutes >= 1 else "<1 min"


def yesno(value: Optional[bool]) -> str:
    if value is None:
        return "—"
    return "Yes" if value else "No"


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


FILTERS = {
    "money": money,
    "number": number,
    "area": area,
    "per_sqm": per_sqm,
    "percent": percent,
    "score_pct": score_pct,
    "distance": distance,
    "orblank": default,
    "verdict_label": verdict_label,
    "confidence_label": confidence_label,
    "similarity_band": similarity_band,
    "investor_attractiveness": investor_attractiveness,
    "benchmark_type_label": benchmark_type_label,
    "walking_time": walking_time,
    "yesno": yesno,
    "span_pct": span_pct,
    "line_chart": line_chart,
}
