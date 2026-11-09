"""Pair each discharge gauging with its stage reading.

Rule: stage = the MeanGageHeight row (00065) on the same field_visit_id and the same time as the
discharge row (00060). A visit can hold several discharges, each with its own MeanGageHeight.
Exact match only: no match -> the discharge is dropped. Two MeanGageHeight rows on the same key
that disagree -> ambiguous, also dropped (identical duplicates are fine). Drop counts are logged
and stored in Dataset.metadata["pairing_dropped"].

Rows with a blank, non-positive, or unparseable stage or discharge are dropped.
Poor measurements taken 2024-09-26..28 (Helene peak, mostly indirect) are kept but marked
excluded so plots show them and the drift test skips them.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from driftwatch.core.schemas import Dataset, Measurement, StablePeriod
from driftwatch.modules.rating_curve.usgs import load_snapshot

log = logging.getLogger(__name__)

STAGE_CODE = "00065"
DISCHARGE_CODE = "00060"
STAGE_READING = "MeanGageHeight"

QUALITY_WEIGHT = {"Excellent": 4.0, "Good": 3.0, "Fair": 2.0, "Poor": 1.0}
DEFAULT_WEIGHT = 1.5
RATED_VALUES = {"Excellent", "Good", "Fair", "Poor"}

EXCLUDE_START = date(2024, 9, 26)
EXCLUDE_END = date(2024, 9, 28)
HELENE_REASON = "Poor measurement at the Helene flood peak (2024-09-26..28)"

DEFAULT_REFERENCE = (date(2012, 1, 1), date(2024, 9, 25))
REFERENCE_WINDOWS = {"02085000": (date(2015, 1, 1), date(2025, 7, 6))}


ReferenceMode = Literal["fixed", "auto"]
REFERENCE_MODES: tuple[str, ...] = ("fixed", "auto")
DEFAULT_REFERENCE_MODE: ReferenceMode = "fixed"
AUTO_TEST_N = 8  # auto: the newest this-many measurements are held out as the test set
AUTO_MIN_N = 20  # the latest stable period is the reference only with this many measurements
AUTO_MIN_YEARS = 2.0  # ... spanning at least this many years; else the previous period is


def reference_window(site: str) -> tuple[date, date]:
    """The fixed reference window (reference_mode='fixed', the default)."""
    return REFERENCE_WINDOWS.get(site, DEFAULT_REFERENCE)


def auto_reference_window(
    periods: list[StablePeriod],
    times: list[datetime],
    test_n: int = AUTO_TEST_N,
    min_n: int = AUTO_MIN_N,
    min_years: float = AUTO_MIN_YEARS,
) -> tuple[date, date, str] | None:
    """reference_mode='auto'. `periods` and `times` (searched measurement times) come from the
    change-point search on the full history (report.auto_reference).

    - The latest stable period has >= min_n measurements spanning >= min_years: it is the
      reference, with its window cut off before the newest `test_n` measurements (those are the
      test set; a gauging on the same day as the first of them joins it). Returns
      (start, the day before the test set starts, "latest").
    - Otherwise the previous stable period is the reference, whole, and everything after it is
      tested. Returns (start, end, "previous").
    - None when there is no previous period to fall back to (the caller keeps the fixed window).
    """
    ps = sorted(periods, key=lambda p: p.start)
    if not ps:
        return None
    latest = ps[-1]
    span_years = (latest.end - latest.start).total_seconds() / (365.25 * 86400)
    ts = sorted(times)
    if latest.n >= min_n and span_years >= min_years and len(ts) > test_n:
        # End the day before the test set's first measurement, so same-day gaugings stay
        # together and the test set holds at least the newest test_n.
        return latest.start.date(), ts[-test_n].date() - timedelta(days=1), "latest"
    if len(ps) >= 2:
        return ps[-2].start.date(), ps[-2].end.date(), "previous"
    return None


def quality_weight(rated: str | None) -> float:
    return QUALITY_WEIGHT.get(rated or "", DEFAULT_WEIGHT)


def _parse_time(s: str) -> datetime:
    """ISO timestamp -> aware UTC datetime. Naive timestamps are refused, not assumed UTC."""
    t = datetime.fromisoformat(s)  # 3.11+ accepts a trailing Z
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"timestamp without a UTC offset: {s!r}")
    return t.astimezone(UTC)


def _parse_value(s: str | None) -> float | None:
    if s is None or not str(s).strip():
        return None
    try:
        return float(s)
    except ValueError:
        return None


def site_name(snapshot: dict) -> str | None:
    locs = snapshot["collections"].get("monitoring-locations") or []
    if not locs:
        return None
    return locs[0].get("properties", {}).get("monitoring_location_name")


def pair_with_counts(snapshot: dict) -> tuple[list[Measurement], dict[str, int]]:
    """One Measurement per usable discharge row, sorted by time, plus counts of dropped rows."""
    site = snapshot["site"]
    props = [f.get("properties", {}) for f in snapshot["collections"]["field-measurements"]]

    stages: dict[tuple[str, datetime], set[float]] = {}
    for p in props:
        if p.get("parameter_code") == STAGE_CODE and p.get("reading_type") == STAGE_READING:
            v = _parse_value(p.get("value"))
            if v is not None and p.get("time"):
                stages.setdefault((p["field_visit_id"], _parse_time(p["time"])), set()).add(v)

    dropped = {"no_exact_stage": 0, "ambiguous_stage": 0, "bad_value": 0}
    out: list[Measurement] = []
    for p in props:
        if p.get("parameter_code") != DISCHARGE_CODE or not p.get("time"):
            continue
        q = _parse_value(p.get("value"))
        if q is None or q <= 0:
            dropped["bad_value"] += 1
            continue
        t = _parse_time(p["time"])
        hs = stages.get((p.get("field_visit_id"), t))
        if not hs:
            dropped["no_exact_stage"] += 1
            continue
        if len(hs) > 1:
            dropped["ambiguous_stage"] += 1
            continue
        h = next(iter(hs))
        if h <= 0:
            dropped["bad_value"] += 1
            continue
        rated = p.get("measurement_rated")
        rated = rated if rated in RATED_VALUES else "Unspecified"
        excluded = rated == "Poor" and EXCLUDE_START <= t.date() <= EXCLUDE_END
        out.append(
            Measurement(
                site=site,
                field_visit_id=p["field_visit_id"],
                time=t,
                stage_ft=h,
                discharge_cfs=q,
                rated=rated,
                weight=quality_weight(rated),
                control_condition=p.get("control_condition"),
                approval_status=p.get("approval_status"),
                pairing="exact",
                excluded=excluded,
                exclude_reason=HELENE_REASON if excluded else None,
            )
        )
    out.sort(key=lambda m: m.time)
    log.info(
        "%s: paired %d discharges; dropped %d (no exact stage %d, ambiguous stage %d, "
        "bad value %d)",
        site,
        len(out),
        sum(dropped.values()),
        dropped["no_exact_stage"],
        dropped["ambiguous_stage"],
        dropped["bad_value"],
    )
    return out, dropped


def pair_measurements(snapshot: dict) -> list[Measurement]:
    return pair_with_counts(snapshot)[0]


def build_dataset(snapshot: dict, source: str = "snapshot") -> Dataset:
    site = snapshot["site"]
    start, end = reference_window(site)
    fetched = snapshot.get("fetched_at")
    measurements, dropped = pair_with_counts(snapshot)
    return Dataset(
        site=site,
        site_name=site_name(snapshot),
        source=source,
        fetched_at=_parse_time(fetched) if fetched else None,
        reference_start=start,
        reference_end=end,
        measurements=measurements,
        metadata={"pairing_dropped": dropped},
    )


def load_dataset(site: str, source: str = "snapshot") -> Dataset:
    if source != "snapshot":
        raise ValueError("only SOURCE=snapshot is supported for reports; run make snapshot first")
    return build_dataset(load_snapshot(site), source)
