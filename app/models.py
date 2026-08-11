"""Pydantic models for the evaluation payload and API responses.

The schema is intentionally permissive (``extra="allow"`` on nested models) so
the upstream evaluation service can evolve its payload without breaking report
generation. Templates only read the fields they know about, and every optional
section is designed to be hidden cleanly when its data isn't provided.

Field names are aligned with estima-backend's internal report schema
(``src/services/reports/schema.py``) — e.g. ``floor_area``/``land_area``,
``deal_type``, ``layout``, ``similarity_score`` — so a future live integration
needs no translation layer.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


# --------------------------------------------------------------------------- #
# Property metadata
# --------------------------------------------------------------------------- #
class PropertyMetadata(_Model):
    title: Optional[str] = None
    deal_type: Optional[str] = None  # "sale" | "rent"
    property_type: Optional[str] = None
    layout: Optional[str] = None  # e.g. "3+kk"

    address: Optional[str] = None
    locality: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    floor_area: Optional[float] = None
    land_area: Optional[float] = None
    rooms: Optional[float] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None

    floor: Optional[str] = None
    total_floors: Optional[int] = None
    elevator: Optional[bool] = None
    balcony: Optional[bool] = None
    loggia: Optional[bool] = None
    terrace: Optional[bool] = None
    cellar: Optional[bool] = None
    parking: Optional[str] = None
    ownership_type: Optional[str] = None
    building_type: Optional[str] = None
    construction_year: Optional[int] = None
    reconstruction_year: Optional[int] = None
    energy_rating: Optional[str] = None
    condition: Optional[str] = None

    source: Optional[str] = None
    source_url: Optional[str] = None
    first_seen_at: Optional[date] = None
    last_seen_at: Optional[date] = None
    days_on_market: Optional[int] = None

    description: Optional[str] = None
    features: List[str] = Field(default_factory=list)
    images: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Pricing & valuation
# --------------------------------------------------------------------------- #
class Pricing(_Model):
    currency: str = "EUR"
    list_price: Optional[float] = None
    price_per_sqm: Optional[float] = None


class PriceRange(_Model):
    low: Optional[float] = None
    mid: Optional[float] = None
    high: Optional[float] = None


class Valuation(_Model):
    estimated_value: Optional[float] = None
    estimated_price_per_sqm: Optional[float] = None
    confidence: Optional[float] = None  # 0..1
    methodology: Optional[str] = None
    recommended_price_range: Optional[PriceRange] = None
    negotiation_zone: Optional[PriceRange] = None

    local_median_price: Optional[float] = None
    local_median_price_per_sqm: Optional[float] = None
    sample_size: Optional[int] = None
    why_this_estimate: List[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Comparables
# --------------------------------------------------------------------------- #
class Comparable(_Model):
    label: Optional[str] = None
    locality: Optional[str] = None
    layout: Optional[str] = None
    floor_area: Optional[float] = None
    price: Optional[float] = None
    price_per_sqm: Optional[float] = None
    adjusted_price_per_sqm: Optional[float] = None
    price_difference_vs_subject: Optional[float] = None
    similarity_score: Optional[float] = None  # 0..100
    source: Optional[str] = None
    source_url: Optional[str] = None
    is_subject: bool = False
    is_median: bool = False

    distance_km: Optional[float] = None
    days_on_market: Optional[int] = None
    price_change: Optional[float] = None


# --------------------------------------------------------------------------- #
# Market benchmarks
# --------------------------------------------------------------------------- #
class MarketBenchmark(_Model):
    name: Optional[str] = None
    benchmark_type: Optional[str] = None  # listing_asking | realized_sale | newbuild_asking | rent_monthly
    value_per_sqm: Optional[float] = None
    source: Optional[str] = None
    # Geographic scope and period the index covers — rendered so a macro
    # reference is never mistaken for a figure about this property. Callers
    # that pack both into `source` still render (fallback in the template).
    scope: Optional[str] = None  # e.g. "Praha 6" or the city fallback
    period: Optional[str] = None  # display form, e.g. "Q3 2024"


# --------------------------------------------------------------------------- #
# Market statistics (regional price series, e.g. NBS for Slovakia)
# --------------------------------------------------------------------------- #
class MarketStatPoint(_Model):
    period: Optional[str] = None  # e.g. "1Q 2026" or "2024"
    value: Optional[float] = None  # price per m² in the payload currency


class MarketDistribution(_Model):
    """Spread of price/m² across the local comparable segment."""

    scope: Optional[str] = None  # e.g. "3-room flats, Bratislava"
    min_price_per_sqm: Optional[float] = None
    p25_price_per_sqm: Optional[float] = None
    median_price_per_sqm: Optional[float] = None
    p75_price_per_sqm: Optional[float] = None
    max_price_per_sqm: Optional[float] = None
    sample_size: Optional[int] = None


class MarketStatistics(_Model):
    """Official/aggregated market statistics for the property's region.

    The section renders when a series or headline figure is present; the
    subject property is marked on the chart via ``subject_price_per_sqm``
    (falling back to ``pricing.price_per_sqm`` in the template).
    """

    region: Optional[str] = None  # e.g. "Bratislava Region"
    country: Optional[str] = None  # e.g. "Slovakia"
    scope_note: Optional[str] = None  # e.g. "All residential, NBS regional series"
    source: Optional[str] = None
    period: Optional[str] = None  # latest period label, e.g. "1Q 2026"

    average_price_per_sqm: Optional[float] = None  # latest market average
    yoy_change: Optional[float] = None  # signed %, e.g. 10.3
    price_index: Optional[float] = None  # index value (base = 100)
    index_base_period: Optional[str] = None  # e.g. "2002"

    series: List[MarketStatPoint] = Field(default_factory=list)
    distribution: Optional[MarketDistribution] = None
    subject_price_per_sqm: Optional[float] = None


# --------------------------------------------------------------------------- #
# Rent & investment analysis
# --------------------------------------------------------------------------- #
class MortgageScenario(_Model):
    rate: Optional[float] = None
    monthly_payment: Optional[float] = None
    coverage_ratio: Optional[float] = None


class RentInvestment(_Model):
    estimated_rent_month: Optional[float] = None
    rent_per_sqm_month: Optional[float] = None
    gross_yield: Optional[float] = None
    net_yield: Optional[float] = None
    vacancy_rate: Optional[float] = None
    maintenance_cost: Optional[float] = None
    service_charges: Optional[float] = None
    tax_fees: Optional[float] = None
    mortgage_sensitivity: List[MortgageScenario] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Buy-vs-rent wealth projection (computed upstream; rendered as-is)
# --------------------------------------------------------------------------- #
class WealthPoint(_Model):
    year: Optional[int] = None
    buyer: Optional[float] = None
    renter: Optional[float] = None


class BuyVsRentAssumptions(_Model):
    property_price: Optional[float] = None
    monthly_rent: Optional[float] = None
    rent_source: Optional[str] = None
    mortgage_rate_pct: Optional[float] = None
    ltv_pct: Optional[float] = None
    term_years: Optional[int] = None
    inflation_pct: Optional[float] = None
    investment_return_pct: Optional[float] = None
    property_growth_pct: Optional[float] = None
    growth_source: Optional[str] = None


class BuyVsRent(_Model):
    horizon_years: Optional[int] = None
    assumptions: BuyVsRentAssumptions = Field(default_factory=BuyVsRentAssumptions)
    down_payment: Optional[float] = None
    monthly_payment: Optional[float] = None
    series: List[WealthPoint] = Field(default_factory=list)
    buyer_final: Optional[float] = None
    renter_final: Optional[float] = None
    breakeven_year: Optional[int] = None


# --------------------------------------------------------------------------- #
# Location & nearby facilities
# --------------------------------------------------------------------------- #
class FacilityCount(_Model):
    category: Optional[str] = None  # transport, groceries, schools, parks, restaurants, health
    count: Optional[int] = None  # None = not computed, 0 = confirmed zero found
    nearest_distance_km: Optional[float] = None


class POI(_Model):
    name: Optional[str] = None
    category: Optional[str] = None
    distance_km: Optional[float] = None
    walking_time_min: Optional[float] = None


class LocationFacilities(_Model):
    available: bool = False
    map_image_url: Optional[str] = None
    facilities: List[FacilityCount] = Field(default_factory=list)
    nearest_pois: List[POI] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Vision / photo-quality analysis
# --------------------------------------------------------------------------- #
class ImageMetric(_Model):
    """Per-photo technical metrics (0–100), matched to ``property.images``.

    Matching is by ``url`` when present, else by list position. Like the
    gallery-level scores these measure the photograph, never the property.
    """

    url: Optional[str] = None
    photo_quality: Optional[float] = None
    brightness: Optional[float] = None
    sharpness: Optional[float] = None
    note: Optional[str] = None


class VisionAnalysis(_Model):
    """Photo-quality metrics for the listing gallery.

    Upstream analysis is local and deterministic: it measures the
    PHOTOGRAPHS (brightness, sharpness, resolution), never the property's
    condition or materials. The deprecated semantic fields below are still
    accepted for old payloads but the templates no longer render them.
    """

    available: bool = False
    summary: Optional[str] = None
    brightness: Optional[float] = None
    sharpness: Optional[float] = None
    photo_quality: Optional[float] = None
    gallery_size: Optional[int] = None
    observations: List[str] = Field(default_factory=list)  # measurable, human-readable
    images: List[str] = Field(default_factory=list)
    image_metrics: List[ImageMetric] = Field(default_factory=list)

    # DEPRECATED — semantic claims local analysis cannot support; ignored by
    # the templates, kept only so historic payloads still validate.
    overall_condition_score: Optional[float] = None  # 0..1 or 0..100
    renovation_score: Optional[float] = None
    detected_features: List[str] = Field(default_factory=list)
    price_adjustment: Optional[float] = None


# --------------------------------------------------------------------------- #
# Indicative condition assessment (payload-supplied)
# --------------------------------------------------------------------------- #
class ConditionItem(_Model):
    """One assessed element of the property (floors, walls, kitchen, …)."""

    element: Optional[str] = None
    state: Optional[str] = None
    note: Optional[str] = None


class ConditionAssessment(_Model):
    """Indicative element-by-element condition assessment.

    Authored UPSTREAM (an agent, or a capable vision model) and rendered
    as-is with an explicit "from listing photos, verify in person" footnote.
    Deliberately separate from :class:`VisionAnalysis`, whose local pixel
    metrics cannot honestly judge condition and never populate this block.
    """

    available: bool = False
    source: Optional[str] = None
    items: List[ConditionItem] = Field(default_factory=list)
    summary: Optional[str] = None
    # Headline renovation/condition score for buyers (0–100 + short label),
    # authored upstream like the rest of this block — never computed locally.
    overall_score: Optional[float] = None
    overall_label: Optional[str] = None


# --------------------------------------------------------------------------- #
# Risk & due diligence
# --------------------------------------------------------------------------- #
class RiskDueDiligence(_Model):
    verified: bool = False
    ownership_type: Optional[str] = None
    cadastre_checked: Optional[bool] = None
    liens_easements: Optional[str] = None
    cooperative_ownership: Optional[bool] = None
    flood_zone: Optional[str] = None
    noise_exposure: Optional[str] = None
    building_condition: Optional[str] = None
    hoa_fees: Optional[float] = None
    reserve_fund: Optional[float] = None


# --------------------------------------------------------------------------- #
# Summary / final recommendation
# --------------------------------------------------------------------------- #
class ReportSummary(_Model):
    headline: Optional[str] = None
    recommendation: Optional[str] = None
    action: Optional[str] = None  # buy | negotiate | avoid | inspect_further
    suggested_offer_range: Optional[PriceRange] = None
    strengths: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    next_steps: List[str] = Field(default_factory=list)
    agent_notes: Optional[str] = None


# --------------------------------------------------------------------------- #
# Methodology
# --------------------------------------------------------------------------- #
class Methodology(_Model):
    valuation_date: Optional[date] = None
    model_version: Optional[str] = None
    model_run_id: Optional[str] = None
    data_freshness_note: Optional[str] = None


# --------------------------------------------------------------------------- #
# Branding
# --------------------------------------------------------------------------- #
class AgencyBranding(_Model):
    name: Optional[str] = None
    logo_url: Optional[str] = None
    primary_color: Optional[str] = None
    accent_color: Optional[str] = None
    agent_name: Optional[str] = None
    agent_email: Optional[str] = None
    agent_phone: Optional[str] = None
    website: Optional[str] = None
    footer_text: Optional[str] = None


# --------------------------------------------------------------------------- #
# Render options
# --------------------------------------------------------------------------- #
class RenderOptions(_Model):
    template: Optional[str] = None  # template style dir, e.g. "default"
    language: Optional[str] = None  # e.g. "en"


# --------------------------------------------------------------------------- #
# Top-level request
# --------------------------------------------------------------------------- #
class EvaluationPayload(_Model):
    """The complete evaluation document consumed by this service."""

    report_title: Optional[str] = None
    generated_at: Optional[datetime] = None

    property: PropertyMetadata = Field(default_factory=PropertyMetadata)
    pricing: Pricing = Field(default_factory=Pricing)
    valuation: Valuation = Field(default_factory=Valuation)
    comparables: List[Comparable] = Field(default_factory=list)
    benchmarks: List[MarketBenchmark] = Field(default_factory=list)
    market_statistics: Optional[MarketStatistics] = None
    rent_investment: Optional[RentInvestment] = None
    buy_vs_rent: Optional[BuyVsRent] = None
    location_facilities: LocationFacilities = Field(default_factory=LocationFacilities)
    vision_analysis: VisionAnalysis = Field(default_factory=VisionAnalysis)
    condition_assessment: Optional[ConditionAssessment] = None
    risk: Optional[RiskDueDiligence] = None
    summary: ReportSummary = Field(default_factory=ReportSummary)
    methodology: Optional[Methodology] = None

    branding: Optional[AgencyBranding] = None
    options: RenderOptions = Field(default_factory=RenderOptions)


# --------------------------------------------------------------------------- #
# API responses
# --------------------------------------------------------------------------- #
class GenerateResponse(BaseModel):
    report_id: str
    status: str = "completed"
    html_url: str
    pdf_url: str
    created_at: datetime


class ReportInfo(BaseModel):
    report_id: str
    status: str
    created_at: datetime
    html_url: str
    pdf_url: str
    template: str
    language: str
    property_title: Optional[str] = None
