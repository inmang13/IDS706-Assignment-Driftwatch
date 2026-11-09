"""Slow drift inside the latest stable segment: a weighted Theil-Sen trend of the % residual.

The change-point search (segmentation.py) finds steps. A channel that creeps (slow fill, a bar
growing, vegetation spreading year on year) gives no step, only a slope. This module fits that
slope on the measurements after the last accepted shift (the latest stable period of the %
series), or on the whole series from the reference start when there is no shift.

- Slope: weighted Theil-Sen, the weighted median of every pairwise slope
  (r_j - r_i) / (t_j - t_i), pair weight w_i * w_j (Measurement.weight by default), in % per year.
- CI: 95 % percentile bootstrap, 2,000 resamples of the measurements, seed 7.
- p-value: two-sided Mann-Kendall (normal approximation, tie-corrected variance, continuity
  correction), unweighted.
- significant = p < 0.01 and |slope| >= 0.75 %/yr and the CI excludes zero.

Sign convention (rating.py): residual_pct = (Q_meas - Q_curve) / Q_curve x 100, so a negative
slope means the gauge measures less flow each year than the curve predicts ("lower").
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
from scipy.stats import norm

from driftwatch.core.schemas import Dataset, DriftResult, Relationship, TrendResult
from driftwatch.modules.rating_curve import rating, segmentation

__all__ = ["TrendResult", "fit_trend", "mann_kendall_p", "site_trend", "trend_measurements"]

MIN_N = 12
MIN_SPAN_YEARS = 3.0
N_BOOT = 2000
SEED = 7
ALPHA = 0.01
MIN_SLOPE_PCT_PER_YEAR = 0.75
DAYS_PER_YEAR = 365.25
_BATCH = 100  # bootstrap resamples per vectorized batch (memory: _BATCH x n(n-1)/2 floats)


def _weighted_median_rows(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Row-wise lower weighted median of x (NaN entries ignored by giving them zero weight)."""
    w = np.where(np.isnan(x), 0.0, w)
    x = np.where(np.isnan(x), np.inf, x)
    order = np.argsort(x, axis=1)
    xs = np.take_along_axis(x, order, axis=1)
    cw = np.cumsum(np.take_along_axis(w, order, axis=1), axis=1)
    half = cw[:, -1:] / 2.0
    idx = np.argmax(cw >= half, axis=1)
    out = xs[np.arange(len(xs)), idx]
    return np.where(cw[:, -1] > 0, out, np.nan)


def _theil_sen_rows(t: np.ndarray, y: np.ndarray, w: np.ndarray, ii, jj) -> np.ndarray:
    """Weighted Theil-Sen slope for each row of (t, y, w), shape (rows, n). Pairs with equal
    times are skipped."""
    dt = t[:, jj] - t[:, ii]
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(dt != 0, (y[:, jj] - y[:, ii]) / dt, np.nan)
    return _weighted_median_rows(s, w[:, ii] * w[:, jj])


def mann_kendall_p(t: np.ndarray, y: np.ndarray) -> float:
    """Two-sided Mann-Kendall p-value of y against t (order by t; tied times contribute 0)."""
    n = len(y)
    ii, jj = np.triu_indices(n, k=1)
    s = float(np.sum(np.sign(y[jj] - y[ii]) * np.sign(t[jj] - t[ii])))
    _, counts = np.unique(y, return_counts=True)
    var = (n * (n - 1) * (2 * n + 5) - np.sum(counts * (counts - 1) * (2 * counts + 5))) / 18.0
    if var <= 0:
        return 1.0
    z = (s - np.sign(s)) / np.sqrt(var)
    return float(2.0 * norm.sf(abs(z)))


def _text(slope: float, significant: bool, start: datetime, n: int) -> str:
    if significant:
        word = "lower" if slope < 0 else "higher"
        return (
            f"Readings have drifted about {abs(slope):.1f} % {word} each year since "
            f"{start.year} ({n} measurements)."
        )
    return f"Readings show no clear drift up or down since {start.year} ({n} measurements)."


def fit_trend(
    times,
    residual_pct,
    weights=None,
    min_n: int = MIN_N,
    min_span_years: float = MIN_SPAN_YEARS,
) -> TrendResult | None:
    """Trend of residual_pct (%) against time. times: datetimes. None when there are fewer than
    min_n usable points or they span less than min_span_years."""
    times = list(times)
    y = np.asarray(residual_pct, dtype=float)
    w = np.ones(len(y)) if weights is None else np.asarray(weights, dtype=float)
    if not (len(times) == len(y) == len(w)):
        raise ValueError("times, residual_pct and weights must have the same length")
    ok = np.isfinite(y) & np.isfinite(w) & (w > 0)
    times = [tm for tm, k in zip(times, ok, strict=True) if k]
    y, w = y[ok], w[ok]
    n = len(y)
    if n < min_n:
        return None
    order = np.argsort([tm.timestamp() for tm in times], kind="stable")
    times = [times[i] for i in order]
    y, w = y[order], w[order]
    t0 = times[0]
    t = np.array([(tm - t0).total_seconds() / 86400.0 / DAYS_PER_YEAR for tm in times])
    span = float(t[-1] - t[0])
    if span < min_span_years:
        return None

    ii, jj = np.triu_indices(n, k=1)
    slope = float(_theil_sen_rows(t[None, :], y[None, :], w[None, :], ii, jj)[0])

    rng = np.random.default_rng(SEED)
    boot = np.empty(N_BOOT)
    for lo in range(0, N_BOOT, _BATCH):
        k = min(_BATCH, N_BOOT - lo)
        idx = rng.integers(0, n, size=(k, n))
        boot[lo : lo + k] = _theil_sen_rows(t[idx], y[idx], w[idx], ii, jj)
    boot = boot[np.isfinite(boot)]
    ci_low, ci_high = (float(v) for v in np.percentile(boot, [2.5, 97.5]))

    p = mann_kendall_p(t, y)
    significant = bool(
        p < ALPHA and abs(slope) >= MIN_SLOPE_PCT_PER_YEAR and (ci_low > 0 or ci_high < 0)
    )
    return TrendResult(
        slope_pct_per_year=round(slope, 3),
        ci_low=round(ci_low, 3),
        ci_high=round(ci_high, 3),
        p_value=float(f"{p:.4g}"),
        n=n,
        span_years=round(span, 2),
        significant=significant,
        window_start=times[0],
        window_end=times[-1],
        text=_text(slope, significant, times[0], n),
    )


def trend_measurements(ds: Dataset, rel: Relationship, drift: DriftResult):
    """The trend window: the change-point search series (Poor left out, Helene-excluded and
    stage <= e out) inside the latest stable period of the % series, i.e. after the last
    accepted shift; with no shift that period is the whole series from the reference start."""
    ms = segmentation.search_measurements(ds, rel)
    if drift.stable_periods:
        start = drift.stable_periods[-1].start
        ms = [m for m in ms if m.time >= start]
    return ms


def site_trend(ds: Dataset, rel: Relationship, drift: DriftResult, **kw) -> TrendResult | None:
    """fit_trend on the latest stable segment of one gauge, quality weights from the gaugings."""
    ms = trend_measurements(ds, rel, drift)
    pct = rating.residual_pct(rel, [m.stage_ft for m in ms], [m.discharge_cfs for m in ms])
    return fit_trend([m.time for m in ms], pct, [m.weight for m in ms], **kw)
