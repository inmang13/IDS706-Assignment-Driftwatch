"""Glass-box trust score (plan §4). Module-agnostic: callers pass plain numbers, every rule is here.

score = 100 - residual (0-50) - staleness (0-20) - quality (0-15) - field notes (0-15)
            - insufficient data (0-10)
Bands: Trusted >= 80 · Watch 50-79 · Stale < 50. All five deductions are always listed, with the
number that drove them, even when they cost 0 points.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from driftwatch.core.schemas import Deduction, TrustScore

RESIDUAL_MAX = 50.0  # Grace 2026-11-07: "score cap is 50" (was 40)
RESIDUAL_POINTS_PER_PCT = 2.0  # per % of median error beyond the gauge's normal scatter
STALE_MAX = 20.0
STALE_GRACE_DAYS = 90  # a visit every ~6-8 weeks is normal
STALE_FULL_DAYS = 365
QUALITY_MAX = 15.0
QUALITY_COST = {"Excellent": 0.0, "Good": 0.0, "Fair": 1 / 3, "Poor": 1.0}
QUALITY_COST_DEFAULT = 0.5  # Unspecified
NOTES_MAX = 15.0
DATA_MAX = 10.0
DATA_POINTS_PER_MISSING = 2.5
DATA_TARGET_PER_YEAR = 4


@dataclass
class TrustInputs:
    recent_residual_pct: Sequence[float]  # current level: latest stable period, newest N
    normal_scatter_pct: float  # median |residual| inside the reference window
    days_since_last: float | None  # None = never measured
    recent_rated: Sequence[str]
    field_flags: Sequence[tuple[str, float]] = field(default_factory=list)  # (note, points)
    n_last_year: int = 0  # every field measurement, including Helene-excluded flood gaugings


def residual_deduction(recent: Sequence[float], normal: float) -> Deduction:
    if len(recent) == 0:
        return Deduction(name="residual", points=0, reason="0 recent measurements to compare.")
    med = float(np.median(recent))
    excess = max(0.0, abs(med) - normal)
    pts = min(RESIDUAL_MAX, RESIDUAL_POINTS_PER_PCT * excess)
    direction = "more" if med > 0 else "less"
    return Deduction(
        name="residual",
        points=round(pts, 1),
        reason=f"Recent measurements carry {abs(med):.1f} % {direction} water than the rating "
        f"predicts (median of {len(recent)}); this gauge's normal scatter is {normal:.1f} %, so "
        f"{excess:.1f} % is excess at {RESIDUAL_POINTS_PER_PCT:g} points per % "
        f"(cap {RESIDUAL_MAX:g}).",
    )


def staleness_deduction(days: float | None) -> Deduction:
    if days is None:
        return Deduction(name="staleness", points=STALE_MAX, reason="0 measurements on record.")
    frac = (days - STALE_GRACE_DAYS) / (STALE_FULL_DAYS - STALE_GRACE_DAYS)
    pts = STALE_MAX * float(np.clip(frac, 0.0, 1.0))
    return Deduction(
        name="staleness",
        points=round(pts, 1),
        reason=f"Last field measurement was {days:.0f} days ago; deductions start after "
        f"{STALE_GRACE_DAYS} days and reach {STALE_MAX:g} at {STALE_FULL_DAYS}.",
    )


def quality_deduction(rated: Sequence[str]) -> Deduction:
    if len(rated) == 0:
        return Deduction(name="quality", points=0, reason="0 recent measurements to grade.")
    cost = float(np.mean([QUALITY_COST.get(r, QUALITY_COST_DEFAULT) for r in rated]))
    pts = QUALITY_MAX * cost
    counts = {k: sum(1 for r in rated if r == k) for k in ("Poor", "Fair", "Good", "Excellent")}
    other = len(rated) - sum(counts.values())
    parts = [f"{v} {k}" for k, v in counts.items() if v] + ([f"{other} unrated"] if other else [])
    return Deduction(
        name="quality",
        points=round(pts, 1),
        reason=f"Recent measurements rated {', '.join(parts)} (Poor costs 1, unrated 0.5, "
        f"Fair 1/3, Good 0); average {cost:.2f} x {QUALITY_MAX:g}.",
    )


def notes_deduction(flags: Sequence[tuple[str, float]]) -> Deduction:
    if not flags:
        return Deduction(
            name="field_notes", points=0, reason="0 open field-note flags on the control."
        )
    pts = min(NOTES_MAX, sum(p for _, p in flags))
    listed = "; ".join(f"'{n}' ({p:g})" for n, p in flags)
    return Deduction(
        name="field_notes",
        points=round(pts, 1),
        reason=f"Open field-note flags: {listed} (cap {NOTES_MAX:g}).",
    )


def data_deduction(n_last_year: int) -> Deduction:
    missing = max(0, DATA_TARGET_PER_YEAR - n_last_year)
    pts = min(DATA_MAX, DATA_POINTS_PER_MISSING * missing)
    return Deduction(
        name="insufficient_data",
        points=round(pts, 1),
        reason=f"{n_last_year} field measurements in the last 12 months; "
        f"{DATA_TARGET_PER_YEAR} or more costs nothing, each one short costs "
        f"{DATA_POINTS_PER_MISSING:g}.",
    )


def score(inputs: TrustInputs) -> TrustScore:
    return TrustScore.from_deductions(
        [
            residual_deduction(inputs.recent_residual_pct, inputs.normal_scatter_pct),
            staleness_deduction(inputs.days_since_last),
            quality_deduction(inputs.recent_rated),
            notes_deduction(inputs.field_flags),
            data_deduction(inputs.n_last_year),
        ]
    )
