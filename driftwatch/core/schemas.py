"""Pydantic v2 schemas shared by every DriftWatch module, the agents, and the API.

Conventions:
- All datetimes are timezone-aware UTC.
- Rating relationship: Q = a * (H - e) ** b. b and e are fixed from the base fit; drift slides a.
- Residual sign: r = (Q_meas - Q_hat) / Q_hat. Scour -> positive, fill -> negative.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Rated = Literal["Excellent", "Good", "Fair", "Poor", "Unspecified"]
Band = Literal["Trusted", "Watch", "Stale"]
Direction = Literal["positive", "negative"]
NodeName = Literal[
    "run", "triage", "evidence_collector", "hypothesis_ranker", "skeptic", "narrator"
]
EventStatus = Literal["started", "progress", "completed", "error"]

TRUSTED_MIN = 80
WATCH_MIN = 50


def _require_tz(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (UTC)")
    return v


class Measurement(BaseModel):
    """One paired stage/discharge gauging (see modules/rating_curve/pairing.py)."""

    site: str
    field_visit_id: str
    time: datetime
    stage_ft: float
    discharge_cfs: float
    rated: Rated = "Unspecified"
    weight: float = Field(gt=0, default=1.5)  # Excellent 4, Good 3, Fair 2, Poor 1, else 1.5
    pairing: str = "exact"  # always "exact": same field_visit_id and time (no fallback)
    control_condition: str | None = None
    approval_status: str | None = None
    excluded: bool = False  # True = kept for plots, left out of the drift test
    exclude_reason: str | None = None

    _tz = field_validator("time")(_require_tz)


class Dataset(BaseModel):
    site: str
    site_name: str | None = None
    source: Literal["snapshot", "live"]
    fetched_at: datetime | None = None
    reference_start: date
    reference_end: date
    measurements: list[Measurement] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _tz = field_validator("fetched_at")(_require_tz)


class Relationship(BaseModel):
    """Base rating fitted on the reference window."""

    kind: Literal["power_law"] = "power_law"
    a: float
    b: float
    e: float  # gage height of zero flow, ft
    reference_start: date
    reference_end: date
    n: int = Field(ge=0)
    rmse_log: float | None = None

    def discharge(self, stage_ft: float) -> float:
        """Rated discharge; NaN at or below e (a negative base would give a complex number)."""
        if stage_ft <= self.e:
            return float("nan")
        return self.a * (stage_ft - self.e) ** self.b


class StablePeriod(BaseModel):
    start: datetime
    end: datetime
    n: int = Field(ge=0)
    median_residual_pct: float | None = None

    _tz = field_validator("start", "end")(_require_tz)


class Shift(BaseModel):
    time: datetime
    size_pct: float  # % flow error vs base rating
    size_ft: float  # equivalent stage shift, ft
    direction: Direction
    n_after: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)

    _tz = field_validator("time")(_require_tz)

    @model_validator(mode="after")
    def _direction_matches_sign(self) -> Shift:
        if (self.size_pct > 0) != (self.direction == "positive") and self.size_pct != 0:
            raise ValueError(f"direction {self.direction} contradicts size_pct {self.size_pct}")
        return self


class DriftResult(BaseModel):
    site: str
    stable_periods: list[StablePeriod] = Field(default_factory=list)
    shifts: list[Shift] = Field(default_factory=list)
    # Same search on the stage-shift residual in ft (segmentation.py). The two lists can differ.
    stable_periods_ft: list[StablePeriod] = Field(default_factory=list)
    shifts_ft: list[Shift] = Field(default_factory=list)
    # Largest post-reference step in each series, in units of that series' reference scatter.
    step_pct_sigma: float | None = None
    step_ft_sigma: float | None = None
    larger_step_series: Literal["pct", "ft"] | None = None  # None: no post-reference shift
    # After that step: |ft residual| larger in the lowest third of flows than in the top third.
    low_flow_concentrated: bool = False
    n_tested: int = Field(ge=0, default=0)
    n_excluded: int = Field(ge=0, default=0)
    n_invalid_domain: int = Field(ge=0, default=0)  # stage <= e: no rated flow, left out of test
    n_poor_unsearched: int = Field(ge=0, default=0)  # Poor-rated tested gaugings kept out of search
    penalty: float | None = None
    # Magnitude gate: change points with |size_pct| <= this are merged away, not reported.
    min_shift_pct: float | None = None
    n_gated: int = Field(ge=0, default=0)  # % series change points dropped by the gate
    n_gated_ft: int = Field(ge=0, default=0)  # ft series change points dropped by the gate


class Deduction(BaseModel):
    name: str
    points: float = Field(ge=0)
    reason: str


class TrustScore(BaseModel):
    """Glass-box score: 100 minus the listed deductions, floored at 0."""

    score: float = Field(ge=0, le=100)
    band: Band
    deductions: list[Deduction] = Field(default_factory=list)

    @staticmethod
    def band_for(score: float) -> Band:
        if score >= TRUSTED_MIN:
            return "Trusted"
        if score >= WATCH_MIN:
            return "Watch"
        return "Stale"

    @classmethod
    def from_deductions(cls, deductions: list[Deduction]) -> TrustScore:
        score = max(0.0, 100.0 - sum(d.points for d in deductions))
        return cls(score=score, band=cls.band_for(score), deductions=deductions)

    @model_validator(mode="after")
    def _arithmetic_matches(self) -> TrustScore:
        expected = max(0.0, 100.0 - sum(d.points for d in self.deductions))
        if abs(self.score - expected) > 1e-6:
            raise ValueError(f"score {self.score} != 100 - deductions ({expected})")
        if self.band != self.band_for(self.score):
            raise ValueError(f"band {self.band} does not match score {self.score}")
        return self


class TrendResult(BaseModel):
    """Slow drift of the % residual over the latest stable segment (rating_curve/trend.py)."""

    slope_pct_per_year: float
    ci_low: float
    ci_high: float
    p_value: float
    n: int
    span_years: float
    significant: bool
    window_start: datetime
    window_end: datetime
    text: str


class Report(BaseModel):
    site: str
    site_name: str | None = None
    generated_at: datetime
    source: Literal["snapshot", "live"]
    relationship: Relationship
    drift: DriftResult
    trust: TrustScore
    likely_cause: str | None = None
    narrative: str | None = None
    # Weighted median stage shift over the latest stable period (report.suggested_shift).
    # Provisional: a hydrographer confirms before it is applied.
    suggested_shift_ft: float | None = None
    suggested_shift_n: int = Field(ge=0, default=0)
    suggested_shift_label: str = "provisional: a hydrographer confirms"
    # Which reference window the base rating used: "fixed" (pairing.reference_window, default) or
    # "auto" (latest long stable period from the full-history search; report.auto_reference).
    reference_mode: Literal["fixed", "auto"] = "fixed"
    reference_start: date | None = None
    reference_end: date | None = None
    reference_note: str | None = None
    # Held-out test set: searched measurements (Poor left out) after reference_end.
    holdout_n: int = Field(ge=0, default=0)
    holdout_start: datetime | None = None
    holdout_end: datetime | None = None
    # Slow-drift trend (report.build_report(with_trend=True), the CLI report); None when not
    # computed or when the latest stable segment is too short (trend.fit_trend).
    trend: TrendResult | None = None
    trend_note: str | None = None

    _tz = field_validator("generated_at", "holdout_start", "holdout_end")(_require_tz)


class TraceEvent(BaseModel):
    run_id: str
    site: str
    seq: int = Field(ge=0)
    ts: datetime
    node: NodeName
    status: EventStatus
    payload: dict[str, Any] = Field(default_factory=dict)

    _tz = field_validator("ts")(_require_tz)
