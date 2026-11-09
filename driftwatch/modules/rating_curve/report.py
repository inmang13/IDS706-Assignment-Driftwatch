"""Snapshot -> Report for one gauge: pairing, base rating, drift test, trust score, likely cause.

The likely cause here is the deterministic triage call (no LLM). The agents in M2 refine it.

Two sets of measurements, on purpose:
- visits (`visits_since_reference`): every paired gauging from the reference start on, including
  the Helene-excluded flood gaugings and invalid_domain ones. A visit is a visit: these drive
  staleness, the 12-month data count, and field-note flags / note-based causes.
- tested (`segmentation.tested_measurements`): the drift-test series. Helene-excluded and
  invalid_domain gaugings stay out; it drives the fit, the drift test, the recent residual and
  the recent quality grade.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np

from driftwatch.core import trust
from driftwatch.core.schemas import Dataset, DriftResult, Relationship, Report, Shift
from driftwatch.modules.rating_curve import causes, pairing, rating, segmentation, trend

RECENT_N = 8
NOTE_SEVERITY_POINTS = {"light": 3.0, "moderate": 8.0, "heavy": 12.0}
CONTROL_CHANGED_POINTS = 15.0
TREND_IN_REFERENCE_NOTE = (
    "Most of this window is the period the curve was fitted on, so this is a slow slide worth "
    "watching, not a test on new data."
)


def visits_since_reference(ds: Dataset):
    """Every paired gauging from the reference start on, excluded or not, in time order."""
    return [m for m in ds.measurements if m.time.date() >= ds.reference_start]


def recent_measurements(ds: Dataset, rel: Relationship, drift: DriftResult):
    """Newest RECENT_N tested measurements inside the latest stable period."""
    ms = segmentation.tested_measurements(ds, rel)
    if drift.stable_periods:
        start = drift.stable_periods[-1].start
        ms = [m for m in ms if m.time >= start]
    return ms[-RECENT_N:]


DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})  # en, em, minus sign


def note_severity_points(note: str) -> float:
    """Points for a transient note like 'Debris - Moderate'. En/em dashes count as hyphens;
    an unreadable severity falls back to light."""
    sev = note.translate(DASHES).split("-")[-1].strip().lower()
    return NOTE_SEVERITY_POINTS.get(sev, NOTE_SEVERITY_POINTS["light"])


def field_flags(ds: Dataset) -> list[tuple[str, float]]:
    """Open field-note flags: control changes since the reference window, transients only if on
    the latest visit (a later visit without them means they cleared)."""
    visits = visits_since_reference(ds)
    flags: dict[str, float] = {}
    for m in visits:
        note = m.control_condition or ""
        if m.time.date() > ds.reference_end and "control changed" in note.lower():
            flags[note] = CONTROL_CHANGED_POINTS
    if visits:
        note = visits[-1].control_condition or ""
        cause = causes.cause_for_note(note)
        if cause and cause.transient:
            flags[note] = note_severity_points(note)
    return list(flags.items())


def trust_inputs(ds: Dataset, rel: Relationship, drift: DriftResult, as_of: datetime):
    recent = recent_measurements(ds, rel, drift)
    visits = visits_since_reference(ds)
    h = [m.stage_ft for m in recent]
    q = [m.discharge_cfs for m in recent]
    return trust.TrustInputs(
        recent_residual_pct=[float(x) for x in rating.residual_pct(rel, h, q)] if recent else [],
        normal_scatter_pct=rating.mdape(rel, rating.reference_measurements(ds)),
        days_since_last=(as_of - visits[-1].time).total_seconds() / 86400 if visits else None,
        recent_rated=[m.rated for m in recent],
        field_flags=field_flags(ds),
        n_last_year=sum(1 for m in visits if m.time > as_of - timedelta(days=365)),
    )


SUGGESTED_SHIFT_LABEL = "provisional: a hydrographer confirms"


def suggested_shift(ds: Dataset, rel: Relationship, drift: DriftResult) -> tuple[float | None, int]:
    """Quality-weighted median stage shift (ft, USGS sign: add it to the gage reading) over the
    latest stable period of the % series, from the search series (Poor left out)."""
    ms = segmentation.search_measurements(ds, rel)
    if drift.stable_periods:
        start = drift.stable_periods[-1].start
        ms = [m for m in ms if m.time >= start]
    if not ms:
        return None, 0
    ft = rating.stage_shift_ft(rel, [m.stage_ft for m in ms], [m.discharge_cfs for m in ms])
    value = segmentation.weighted_median(ft, [m.weight for m in ms])
    return round(value, 3) + 0.0, len(ms)  # + 0.0 turns -0.0 into 0.0


def top_shift(reference_end: date, drift: DriftResult) -> Shift | None:
    """Largest shift after the reference window (older ones are already in the base rating)."""
    post = [s for s in drift.shifts if s.time.date() > reference_end]
    return max(post, key=lambda s: abs(s.size_pct)) if post else None


def likely_cause(
    ds: Dataset, inputs: trust.TrustInputs, band: str
) -> tuple[str | None, str | None]:
    """(cause key, one-sentence why). None when the gauge is Trusted or the error is in the noise.

    Rules: the direction is the sign of the recent median residual. A field note since the
    reference window whose cause matches that sign wins (persistent before transient). A
    control-changed note that contradicts the sign points to a datum change / rebuild (a
    contradicting debris/vegetation note is just ignored). Otherwise -> the persistent cause for
    that sign (scour or fill), to be checked against channel evidence by the agents.
    """
    if band == "Trusted" or not inputs.recent_residual_pct:
        return None, None
    med = float(np.median(inputs.recent_residual_pct))
    if abs(med) <= inputs.normal_scatter_pct:
        return None, None
    if inputs.n_last_year < trust.DATA_TARGET_PER_YEAR:
        return "insufficient_data", "Too few recent measurements to name a cause."
    direction = "positive" if med > 0 else "negative"
    noted = []
    for m in visits_since_reference(ds):
        c = causes.cause_for_note(m.control_condition)
        if c and m.time.date() > ds.reference_end and c not in noted:
            noted.append(c)
    agree = sorted(
        (c for c in noted if causes.sign_agrees(c, direction)), key=lambda c: c.transient
    )
    word = "more" if med > 0 else "less"
    if agree:
        c = agree[0]
        return c.key, (
            f"Field note says {c.label.lower()}, and the gauge reads {abs(med):.0f} % {word} "
            f"water than rated, which is the direction {c.label.lower()} produces."
        )
    contradicting = [c for c in noted if not c.transient]
    if contradicting:
        names = ", ".join(c.label.lower() for c in contradicting)
        return "datum_change", (
            f"Field notes say {names}, but the gauge reads {abs(med):.0f} % {word} water than "
            f"rated, the opposite of what that would do; a datum change or gauge rebuild (or "
            f"fill) fits the sign better. Check the gauge history."
        )
    c = causes.get_cause("scour" if direction == "positive" else "fill")
    return c.key, (
        f"No field note explains it; {abs(med):.0f} % {word} water than rated is the direction "
        f"{c.label.lower()} produces. Check channel area for confirmation."
    )


def auto_reference(ds: Dataset) -> tuple[Dataset, str]:
    """reference_mode='auto': fit the fixed-window rating, run the change-point search on the
    full history (every non-excluded gauging, any date), then pairing.auto_reference_window:
    the latest stable period cut off before the newest 8 measurements (the test set) when it
    has >= 20 measurements over >= 2 years, else the previous stable period with everything
    after it tested. Returns the dataset with that window and a note; falls back to the fixed
    window (said in the note) when there is no previous period or the window cannot be fitted."""
    fixed = (ds.reference_start, ds.reference_end)
    rel = rating.fit_rating(ds)
    full = segmentation.drift_test(ds, rel, series_start=date.min)
    times = [m.time for m in segmentation.search_measurements(ds, rel, date.min)]
    picked = pairing.auto_reference_window(full.stable_periods, times)
    if picked is None:
        return ds, "auto: only one stable period and it is too short to cut; fixed window kept"
    start, end, which = picked
    moved = ds.model_copy(update={"reference_start": start, "reference_end": end})
    try:
        rating.fit_rating(moved)
    except rating.FitError as exc:
        return ds, f"auto: window {start}..{end} could not be fitted ({exc}); fixed window kept"
    if which == "latest":
        how = (
            f"latest stable period, cut off before the newest {pairing.AUTO_TEST_N} "
            f"measurements (the test set)"
        )
    else:
        how = (
            f"previous stable period (the latest has < {pairing.AUTO_MIN_N} measurements or "
            f"spans < {pairing.AUTO_MIN_YEARS:g} years); everything after it is tested"
        )
    return moved, f"auto: {how}; fixed window was {fixed[0]}..{fixed[1]}"


def holdout(ds: Dataset, rel: Relationship) -> tuple[int, datetime | None, datetime | None]:
    """The test set: searched measurements (Poor left out) after the reference window."""
    ms = [m for m in segmentation.search_measurements(ds, rel) if m.time.date() > ds.reference_end]
    return len(ms), (ms[0].time if ms else None), (ms[-1].time if ms else None)


def build_report(
    site: str,
    source: str = "snapshot",
    ds: Dataset | None = None,
    reference_mode: str = pairing.DEFAULT_REFERENCE_MODE,
    with_trend: bool = False,
) -> Report:
    """with_trend runs the slow-drift trend (trend.site_trend, a 2,000-resample bootstrap) and
    fills Report.trend / trend_note. Off by default so the API and the agents stay fast; the CLI
    report turns it on. It never feeds the trust score."""
    if reference_mode not in pairing.REFERENCE_MODES:
        raise ValueError(f"reference_mode must be one of {pairing.REFERENCE_MODES}")
    ds = ds or pairing.load_dataset(site, source)
    note = None
    if reference_mode == "auto":
        ds, note = auto_reference(ds)
    rel = rating.fit_rating(ds)
    drift = segmentation.drift_test(ds, rel)
    as_of = ds.fetched_at or datetime.now(UTC)
    inputs = trust_inputs(ds, rel, drift, as_of)
    ts = trust.score(inputs)
    cause, why = likely_cause(ds, inputs, ts.band)
    shift_ft, shift_n = suggested_shift(ds, rel, drift)
    hold_n, hold_start, hold_end = holdout(ds, rel)
    tr = trend.site_trend(ds, rel, drift) if with_trend else None
    trend_note = (
        TREND_IN_REFERENCE_NOTE
        if tr is not None and tr.window_start.date() < ds.reference_end
        else None
    )
    return Report(
        site=ds.site,
        site_name=ds.site_name,
        generated_at=datetime.now(UTC),
        source=ds.source,
        relationship=rel,
        drift=drift,
        trust=ts,
        likely_cause=cause,
        narrative=why,
        suggested_shift_ft=shift_ft,
        suggested_shift_n=shift_n,
        suggested_shift_label=SUGGESTED_SHIFT_LABEL,
        reference_mode=reference_mode,
        reference_start=ds.reference_start,
        reference_end=ds.reference_end,
        reference_note=note,
        holdout_n=hold_n,
        holdout_start=hold_start,
        holdout_end=hold_end,
        trend=tr,
        trend_note=trend_note,
    )


def summary_line(report: Report) -> str:
    """Station name, band, score, top shift since the reference window."""
    top = top_shift(report.relationship.reference_end, report.drift)
    shift = (
        f"top shift {top.time:%Y-%m-%d} {top.size_pct:+.0f} % ({top.size_ft:+.2f} ft)"
        if top
        else "no shift since the reference window"
    )
    name = report.site_name or report.site
    cause = f" · likely {report.likely_cause}" if report.likely_cause else ""
    n_bad = report.drift.n_invalid_domain
    bad = f" · {n_bad} at or below rating zero (not tested)" if n_bad else ""
    return (
        f"{name} ({report.site}): {report.trust.band} {report.trust.score:.0f} · {shift}"
        f"{cause}{bad}"
    )
