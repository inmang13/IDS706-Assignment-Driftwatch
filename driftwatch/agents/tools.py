"""Evidence tools for the agents. Pure Python over the committed snapshot; no LLM, no web.

Every tool returns a plain JSON-safe dict so it can go straight into a TraceEvent payload and
into an LLM prompt.

channel_geometry_trend is the key one. Channel area, width and velocity are *evidence only*
(never rating predictors: Q = A·V would leak). The question it answers: at the same water level,
did the measuring section get bigger/smaller (area), or does the water just move slower/faster
(velocity)? Speed falling much more than area changing points at something downstream holding
the water back (fill or debris on the control, backwater), not at a gauge datum change.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from statistics import median
from typing import Any

import numpy as np
from scipy.stats import theilslopes

from driftwatch.core.schemas import Dataset, Relationship, Report
from driftwatch.modules.rating_curve import pairing, rating
from driftwatch.modules.rating_curve import report as rc_report
from driftwatch.modules.rating_curve.usgs import load_snapshot

MIN_BEFORE = 5  # channel measurements needed before the shift to fit a trend
MIN_AFTER = 3  # ... and after
HELENE_PEAK = datetime(2024, 9, 27, 12, tzinfo=UTC)


@lru_cache(maxsize=16)
def _snapshot(site: str) -> dict:
    return load_snapshot(site)


@lru_cache(maxsize=16)
def _dataset(site: str) -> Dataset:
    return pairing.build_dataset(_snapshot(site), "snapshot")


@lru_cache(maxsize=16)
def _relationship(site: str) -> Relationship:
    return rating.fit_rating(_dataset(site))


@lru_cache(maxsize=16)
def report(site: str) -> Report:
    """The M1 report for a site, built from the snapshot (same as `make report`, not written)."""
    return rc_report.build_report(site, "snapshot", ds=_dataset(site))


def dataset(site: str) -> Dataset:
    return _dataset(site)


def default_split(site: str) -> datetime:
    """Shift time to split evidence on: the top post-window shift, else the day after the
    reference window ends (the storm, for the Helene gauges)."""
    rep = report(site)
    top = rc_report.top_shift(rep.relationship.reference_end, rep.drift)
    if top:
        return top.time
    d = rep.relationship.reference_end
    return datetime(d.year, d.month, d.day, tzinfo=UTC) + timedelta(days=1)


def _as_dt(t: datetime | date | str | None, site: str) -> datetime:
    if t is None:
        return default_split(site)
    if isinstance(t, str):
        t = datetime.fromisoformat(t)
    if isinstance(t, datetime):
        return t if t.tzinfo else t.replace(tzinfo=UTC)
    return datetime(t.year, t.month, t.day, tzinfo=UTC)


def _num(s: Any) -> float | None:
    try:
        v = float(s)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) and v > 0 else None


def _r(x: float | None, nd: int = 1) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def channel_rows(site: str) -> list[dict[str, Any]]:
    """Channel measurements joined to their paired stage on (field_visit_id, time).

    Rows without area or velocity, unpaired rows, Helene-excluded gaugings and rows at or below
    the rating's zero-flow stage e are left out. If one (visit, time) key holds several channel
    rows (a split channel), the key is dropped: summing them would need a convention the snapshot
    doesn't document. Returns rows sorted by time.
    """
    ds = _dataset(site)
    rel = _relationship(site)
    by_key: dict[tuple[str, datetime], object] = {}
    for m in ds.measurements:  # two discharges on one (visit, time): ambiguous, drop the key
        k = (m.field_visit_id, m.time)
        by_key[k] = None if k in by_key else m
    raw: dict[tuple[str, datetime], list[dict]] = {}
    for f in _snapshot(site)["collections"].get("channel-measurements", []):
        p = f.get("properties", {})
        if not p.get("time") or not p.get("field_visit_id"):
            continue
        key = (p["field_visit_id"], pairing._parse_time(p["time"]))
        raw.setdefault(key, []).append(p)
    rows = []
    for key, ps in raw.items():
        if len(ps) != 1:
            continue
        p = ps[0]
        m = by_key.get(key)
        area, vel = _num(p.get("channel_area")), _num(p.get("channel_velocity"))
        if m is None or m.excluded or area is None or vel is None or m.stage_ft <= rel.e:
            continue
        rows.append(
            {
                "time": key[1],
                "stage_ft": m.stage_ft,
                "area_ft2": area,
                "velocity_fps": vel,
                "width_ft": _num(p.get("channel_width")),
            }
        )
    rows.sort(key=lambda r: r["time"])
    return rows


def _fit_at(x: np.ndarray, y: np.ndarray, x0: float) -> float:
    """Theil-Sen line of y on x (robust to the odd bad gauging), evaluated at x0."""
    slope, intercept, *_ = theilslopes(y, x)
    return float(intercept + slope * x0)


def channel_geometry_trend(site: str, shift_time: datetime | date | str | None = None) -> dict:
    """Area and velocity at the same stage, before vs after the shift.

    Fits ln(area) and ln(velocity) against ln(H - e) separately on channel measurements from the
    reference start up to the shift and from the shift on (e from the base rating), and compares
    the two fits at the median post-shift stage: % difference = exp(after - before) - 1.
    Also reports median width before/after and n of each. `sufficient` is False when either
    side has too few measurements to fit (then the % fields are None).
    """
    split = _as_dt(shift_time, site)
    ds = _dataset(site)
    rel = _relationship(site)
    rows = [r for r in channel_rows(site) if r["time"].date() >= ds.reference_start]
    before = [r for r in rows if r["time"] < split]
    after = [r for r in rows if r["time"] >= split]
    out: dict[str, Any] = {
        "site": site,
        "shift_time": split.isoformat(),
        "e_ft": round(rel.e, 3),
        "n_before": len(before),
        "n_after": len(after),
        "median_width_before_ft": _r(
            median(w) if (w := [r["width_ft"] for r in before if r["width_ft"]]) else None
        ),
        "median_width_after_ft": _r(
            median(w) if (w := [r["width_ft"] for r in after if r["width_ft"]]) else None
        ),
        "at_stage_ft": None,
        "area_change_pct": None,
        "velocity_change_pct": None,
        "sufficient": False,
    }
    if len(before) < MIN_BEFORE or len(after) < MIN_AFTER:
        out["note"] = (
            f"not enough channel measurements to compare (need {MIN_BEFORE} before and "
            f"{MIN_AFTER} after)"
        )
        return out
    h0 = float(median(r["stage_ft"] for r in after))
    x0 = np.log(h0 - rel.e)

    def change(field: str) -> float:
        xb = np.log(np.array([r["stage_ft"] for r in before]) - rel.e)
        yb = np.log(np.array([r[field] for r in before]))
        xa = np.log(np.array([r["stage_ft"] for r in after]) - rel.e)
        ya = np.log(np.array([r[field] for r in after]))
        return (np.exp(_fit_at(xa, ya, x0) - _fit_at(xb, yb, x0)) - 1) * 100

    out.update(
        at_stage_ft=round(h0, 2),
        area_change_pct=_r(change("area_ft2")),
        velocity_change_pct=_r(change("velocity_fps")),
        sufficient=True,
    )
    return out


def field_notes(site: str, since: datetime | date | str | None = None) -> dict:
    """Every visit since `since` (default: end of the reference window) with its control note
    and measurement rating, Helene-excluded flood gaugings included. One row per visit."""
    ds = _dataset(site)
    if since is None:
        since = ds.reference_end
    t0 = _as_dt(since, site)
    rows: dict[str, dict] = {}
    for m in ds.measurements:
        if m.time < t0:
            continue
        r = rows.setdefault(
            m.field_visit_id,
            {
                "time": m.time.isoformat(),
                "note": m.control_condition or "",
                "rated": m.rated,
                "excluded": m.excluded,
            },
        )
        # several discharges per visit: keep the first time, note any non-empty note
        if not r["note"] and m.control_condition:
            r["note"] = m.control_condition
    visits = sorted(rows.values(), key=lambda r: r["time"])
    notes = sorted({v["note"] for v in visits if v["note"] and v["note"].lower() != "clear"})
    return {
        "site": site,
        "since": t0.isoformat(),
        "n_visits": len(visits),
        "distinct_notes": notes,
        "latest_note": visits[-1]["note"] if visits else None,
        "visits": visits,
    }


def flood_context(site: str, shift_time: datetime | date | str | None = None) -> dict:
    """Largest measured discharge between the last tested visit before the shift and the first
    one at/after it, Helene-excluded flood gaugings included, compared to the largest
    reference-window gauging. Empty `peak` when nothing was measured in that gap."""
    split = _as_dt(shift_time, site)
    ds = _dataset(site)
    rel = _relationship(site)
    tested = [
        m
        for m in ds.measurements
        if not m.excluded and m.stage_ft > rel.e and m.time.date() >= ds.reference_start
    ]
    pre = [m for m in tested if m.time < split]
    post = [m for m in tested if m.time >= split]
    lo = pre[-1].time if pre else None
    hi = post[0].time if post else None
    gap = [
        m
        for m in ds.measurements
        if (lo is None or m.time > lo)
        and (hi is None or m.time < hi)
        and m.time.date() >= ds.reference_start
    ]
    ref_max = max((m.discharge_cfs for m in rating.reference_measurements(ds)), default=None)
    out: dict[str, Any] = {
        "site": site,
        "last_pre_shift_visit": lo.isoformat() if lo else None,
        "first_post_shift_visit": hi.isoformat() if hi else None,
        "n_gap_measurements": len(gap),
        "largest_reference_discharge_cfs": ref_max,
        "peak": None,
        # Helene peak (2024-09-27) inside the gap even if nobody measured it
        "helene_in_gap": (lo is None or lo < HELENE_PEAK) and (hi is None or hi > HELENE_PEAK),
    }
    if gap:
        pk = max(gap, key=lambda m: m.discharge_cfs)
        out["peak"] = {
            "time": pk.time.isoformat(),
            "discharge_cfs": pk.discharge_cfs,
            "stage_ft": pk.stage_ft,
            "rated": pk.rated,
            "helene_excluded": pk.excluded,
            "x_largest_reference": _r(pk.discharge_cfs / ref_max, 2) if ref_max else None,
        }
    return out


SITE_FIELDS = (
    "monitoring_location_name",
    "state_name",
    "county_name",
    "drainage_area",
    "altitude",
    "vertical_datum",
    "revision_note",
    "revision_modified",
)


def site_metadata(site: str) -> dict:
    """Station facts from the snapshot's monitoring-locations record."""
    locs = _snapshot(site)["collections"].get("monitoring-locations") or [{}]
    p = locs[0].get("properties", {})
    out = {k: p.get(k) for k in SITE_FIELDS}
    out["site"] = site
    rev = out.get("revision_note") or ""
    out["revision_note"] = rev.replace("&nbsp;", " ")[:600]
    return out
