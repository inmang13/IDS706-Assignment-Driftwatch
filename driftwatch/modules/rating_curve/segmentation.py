"""Darienzo-style recursive segmentation of the rating residual series.

Series: every non-excluded measurement from the start of the reference window onward, in time
order, minus invalid_domain ones (stage <= e, where the rating has no flow; see rating.py). The change-point search runs on ln(Q_meas / Q_hat), standardized by the robust spread
(1.4826 x MAD) of the reference-window residuals, so one penalty means the same thing at a
quiet gauge and a noisy one. PELT (l2 cost, min_size 6) splits the series; each piece is searched
again until no piece splits. Sizes are reported in plain % flow and ft (see rating.py signs).

The search runs twice: on the % flow residual above, and on the stage-shift residual in ft
(also standardized by its reference spread). USGS treats scour and fill as changes to the
zero-flow height, so a step that shows mainly in ft, and mostly at low flows, is a clue for the
agents (`larger_step_series`, `low_flow_concentrated`).

Poor-rated gaugings are left out of the search (they stay in plots and counts). A shift's size
is the step between the quality-weighted median residual (Measurement.weight) of the segment
before and the segment after it. confidence = 1 - Mann-Whitney p-value between those two segments.
"""

from __future__ import annotations

import logging
from datetime import date
from itertools import pairwise

import numpy as np
import ruptures as rpt
from scipy.stats import mannwhitneyu

from driftwatch.core.schemas import (
    Dataset,
    DriftResult,
    Measurement,
    Relationship,
    Shift,
    StablePeriod,
)
from driftwatch.modules.rating_curve import rating

log = logging.getLogger(__name__)

# Chosen from a fixed list (decision log 2026-11-06): any value in 25..150 keeps Eno and
# Swannanoa quiet after Helene and fires on Newport; 50 sits well inside that window.
PENALTY = 50.0
MIN_SIZE = 6

# Magnitude gate (dh 2b): a change point is reported as a shift only if
# |size_pct| > max(GATE_MIN_PCT, GATE_MDAPE_FACTOR x the gauge's reference MdAPE).
GATE_MIN_PCT = 10.0
GATE_MDAPE_FACTOR = 1.5


def shift_gate_pct(ds: Dataset, rel: Relationship) -> float:
    """The smallest |size_pct| a change point needs to count as a shift at this gauge."""
    return max(
        GATE_MIN_PCT, GATE_MDAPE_FACTOR * rating.mdape(rel, rating.reference_measurements(ds))
    )


def candidate_measurements(ds: Dataset, start: date | None = None) -> list[Measurement]:
    """Non-excluded measurements from the reference start (or `start`) on, before the domain
    check. `start=date.min` gives the full history (used to derive the auto reference window)."""
    start = ds.reference_start if start is None else start
    return [m for m in ds.measurements if not m.excluded and m.time.date() >= start]


def tested_measurements(
    ds: Dataset, rel: Relationship, start: date | None = None
) -> list[Measurement]:
    """The drift-test series: candidates whose stage is inside the rating's domain (H > e)."""
    return [m for m in candidate_measurements(ds, start) if m.stage_ft > rel.e]


def search_measurements(
    ds: Dataset, rel: Relationship, start: date | None = None
) -> list[Measurement]:
    """The change-point search series: tested measurements minus every Poor-rated one. Poor
    gaugings stay in `tested_measurements` (plots, counts, the recent quality grade)."""
    return [m for m in tested_measurements(ds, rel, start) if m.rated != "Poor"]


def weighted_median(x, w) -> float:
    """Median of x with weights w (lower weighted median; the two middle values are averaged
    when the cumulative weight lands exactly on half). Equal weights give the plain median."""
    x, w = np.asarray(x, dtype=float), np.asarray(w, dtype=float)
    if not len(x):
        return float("nan")
    order = np.argsort(x, kind="stable")
    x, w = x[order], w[order]
    cw = np.cumsum(w)
    half = cw[-1] / 2.0
    i = int(np.searchsorted(cw, half))
    if np.isclose(cw[i], half) and i + 1 < len(x):
        return float((x[i] + x[i + 1]) / 2.0)
    return float(x[i])


def n_invalid_domain(ds: Dataset, rel: Relationship) -> int:
    return sum(1 for m in candidate_measurements(ds) if m.stage_ft <= rel.e)


def change_points(z: np.ndarray, penalty: float = PENALTY, min_size: int = MIN_SIZE) -> list[int]:
    """Indices where a new segment starts, found by recursive PELT."""
    n = len(z)
    if n < 2 * min_size:
        return []
    algo = rpt.Pelt(model="l2", min_size=min_size, jump=1).fit(z.reshape(-1, 1))
    inner = algo.predict(pen=penalty)[:-1]
    if not inner:
        return []
    edges = [0, *inner, n]
    found: set[int] = set(inner)
    for lo, hi in pairwise(edges):
        found.update(lo + c for c in change_points(z[lo:hi], penalty, min_size))
    return sorted(found)


def _robust_sigma(x: np.ndarray) -> float:
    s = 1.4826 * float(np.median(np.abs(x - np.median(x)))) if len(x) else 0.0
    return s if s > 0 else (float(np.std(x)) or 1.0)


def drift_test(
    ds: Dataset,
    rel: Relationship,
    penalty: float = PENALTY,
    series_start: date | None = None,
    min_shift_pct: float | None = None,
) -> DriftResult:
    """series_start: search from this date instead of the reference start (date.min = the full
    history). The standardization always uses the reference window only.
    min_shift_pct: the magnitude gate; None = `shift_gate_pct` (the default), 0 = no gate."""
    gate = shift_gate_pct(ds, rel) if min_shift_pct is None else float(min_shift_pct)
    tested = tested_measurements(ds, rel, series_start)
    ms = search_measurements(ds, rel, series_start)
    n_excluded = sum(1 for m in ds.measurements if m.excluded)
    n_invalid = n_invalid_domain(ds, rel)
    n_poor = len(tested) - len(ms)
    if not ms:
        return DriftResult(
            site=ds.site,
            n_tested=len(tested),
            n_excluded=n_excluded,
            n_invalid_domain=n_invalid,
            n_poor_unsearched=n_poor,
            penalty=penalty,
            min_shift_pct=round(gate, 2),
        )

    h = np.array([m.stage_ft for m in ms])
    q = np.array([m.discharge_cfs for m in ms])
    log_r = np.log(q / rating.predict_q(rel, h))
    pct = rating.residual_pct(rel, h, q)
    ft = rating.stage_shift_ft(rel, h, q)
    w = np.array([m.weight for m in ms])

    in_ref = np.array([ds.reference_start <= m.time.date() <= ds.reference_end for m in ms])

    def _ref(x: np.ndarray) -> np.ndarray:
        return x[in_ref] if in_ref.any() else x

    # Series 1 (% flow): searched on ln(Q/Q_hat). Series 2 (ft): searched on the stage shift.
    z_pct = (log_r - np.median(_ref(log_r))) / _robust_sigma(_ref(log_r))
    z_ft = (ft - np.median(_ref(ft))) / _robust_sigma(_ref(ft))
    stable, shifts, gated = _segment(ms, z_pct, log_r, pct, ft, w, penalty, gate)
    stable_ft, shifts_ft, gated_ft = _segment(ms, z_ft, ft, pct, ft, w, penalty, gate)
    log.info(
        "%s: shift gate |size_pct| > %.1f %% (max(%g, %g x reference MdAPE)); "
        "dropped %d %% change points, %d ft change points",
        ds.site,
        gate,
        GATE_MIN_PCT,
        GATE_MDAPE_FACTOR,
        gated,
        gated_ft,
    )

    # Which series shows the bigger step after the reference window, in units of its own
    # reference scatter (robust sigma of the % residual / of the ft residual).
    sig_pct, sig_ft = _robust_sigma(_ref(pct)), _robust_sigma(_ref(ft))
    post = [s for s in shifts if s.time.date() > ds.reference_end]
    post_ft = [s for s in shifts_ft if s.time.date() > ds.reference_end]
    best_pct = max(post, key=lambda s: abs(s.size_pct), default=None)
    best_ft = max(post_ft, key=lambda s: abs(s.size_ft), default=None)
    step_pct = abs(best_pct.size_pct) / sig_pct if best_pct else None
    step_ft = abs(best_ft.size_ft) / sig_ft if best_ft else None
    larger, anchor = None, None
    if step_pct is not None or step_ft is not None:
        if step_ft is not None and (step_pct is None or step_ft > step_pct):
            larger, anchor = "ft", best_ft
        else:
            larger, anchor = "pct", best_pct
    low_flow = low_flow_concentrated(ms, q, ft, anchor.time) if anchor else False

    return DriftResult(
        site=ds.site,
        stable_periods=stable,
        shifts=shifts,
        stable_periods_ft=stable_ft,
        shifts_ft=shifts_ft,
        step_pct_sigma=round(step_pct, 2) if step_pct is not None else None,
        step_ft_sigma=round(step_ft, 2) if step_ft is not None else None,
        larger_step_series=larger,
        low_flow_concentrated=low_flow,
        n_tested=len(tested),
        n_excluded=n_excluded,
        n_invalid_domain=n_invalid,
        n_poor_unsearched=n_poor,
        penalty=penalty,
        min_shift_pct=round(gate, 2),
        n_gated=gated,
        n_gated_ft=gated_ft,
    )


def low_flow_concentrated(ms: list[Measurement], q: np.ndarray, ft: np.ndarray, since) -> bool:
    """True when, after the shift, the stage-shift residual (|ft|) is larger in the lowest third
    of measured flows than in the top third. A step in the control's zero-flow height (scour or
    fill of a low-water control) shows this way; a step that slides the whole curve in % shows
    larger in ft at high flows instead. Needs 6 post-shift measurements (2 per third)."""
    idx = np.array([m.time >= since for m in ms])
    qa, fa = q[idx], ft[idx]
    if len(qa) < 6:
        return False
    lo_cut, hi_cut = np.quantile(qa, [1 / 3, 2 / 3])
    low, high = np.abs(fa[qa <= lo_cut]), np.abs(fa[qa >= hi_cut])
    return bool(np.median(low) > np.median(high))


def _step_pct(pct, w, lo, mid, hi) -> float:
    return weighted_median(pct[mid:hi], w[mid:hi]) - weighted_median(pct[lo:mid], w[lo:mid])


def gate_change_points(cps: list[int], n: int, pct, w, gate: float) -> list[int]:
    """Drop change points whose % step is not above the gate, smallest first, recomputing the
    neighbours' steps after each drop (the two segments merge). Returns the survivors."""
    cps = list(cps)
    while cps:
        edges = [0, *cps, n]
        sizes = [
            abs(_step_pct(pct, w, edges[i], edges[i + 1], edges[i + 2])) for i in range(len(cps))
        ]
        i = int(np.argmin(sizes))
        if sizes[i] > gate:
            break
        cps.pop(i)
    return cps


def _segment(ms, z, test_series, pct, ft, w, penalty, gate=0.0):
    """Change points on z -> (stable periods, shifts, n dropped by the gate). Change points with
    a % step not above `gate` are merged away first. Sizes in % and ft are quality-weighted
    medians (weights w) after minus before; confidence from an unweighted Mann-Whitney test on
    test_series (the unstandardized searched series)."""
    raw = change_points(z, penalty)
    cps = gate_change_points(raw, len(ms), pct, w, gate) if gate > 0 else raw
    edges = [0, *cps, len(ms)]
    segments = list(pairwise(edges))

    stable = [
        StablePeriod(
            start=ms[lo].time,
            end=ms[hi - 1].time,
            n=hi - lo,
            median_residual_pct=round(float(np.median(pct[lo:hi])), 2),
        )
        for lo, hi in segments
    ]
    shifts = []
    for (lo, mid), (_, hi) in pairwise(segments):
        size_pct = weighted_median(pct[mid:hi], w[mid:hi]) - weighted_median(pct[lo:mid], w[lo:mid])
        size_ft = weighted_median(ft[mid:hi], w[mid:hi]) - weighted_median(ft[lo:mid], w[lo:mid])
        p = mannwhitneyu(test_series[lo:mid], test_series[mid:hi]).pvalue
        shifts.append(
            Shift(
                time=ms[mid].time,
                size_pct=round(size_pct, 2),
                size_ft=round(size_ft, 3),
                direction="positive" if size_pct > 0 else "negative",
                n_after=len(ms) - mid,  # everything since the shift, not just the next segment
                confidence=round(float(np.clip(1.0 - p, 0.0, 1.0)), 4),
            )
        )
    return stable, shifts, len(raw) - len(cps)
