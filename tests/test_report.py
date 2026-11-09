"""End-to-end on the snapshot: the 'Done means' bands from CLAUDE.md, and the CLI output."""

import json

import pytest

from driftwatch import cli
from driftwatch.core.schemas import Report
from driftwatch.modules.rating_curve import report


@pytest.fixture(scope="module")
def reports():
    sites = ["03459500", "03455000", "03451000", "03463300", "02085000"]
    return {s: report.build_report(s) for s in sites}


@pytest.mark.parametrize("site", ["03459500", "03455000"])
def test_hero_gauges_are_stale_with_a_cause(reports, site):
    rep = reports[site]
    assert rep.trust.band == "Stale"
    assert rep.likely_cause and rep.narrative
    assert report.top_shift(rep.relationship.reference_end, rep.drift).direction == "negative"


def test_newport_cause_is_fill_and_hepco_flags_the_sign_mismatch(reports):
    assert reports["03455000"].likely_cause == "fill"
    hepco = reports["03459500"]
    assert hepco.likely_cause == "datum_change"
    assert "scour" in hepco.narrative and "opposite" in hepco.narrative


@pytest.mark.parametrize("site", ["03451000", "03463300", "02085000"])
def test_controls_are_trusted_with_no_invented_cause(reports, site):
    rep = reports[site]
    assert rep.trust.band == "Trusted"
    assert rep.likely_cause is None


def test_every_deduction_has_a_reason_with_a_number(reports):
    for rep in reports.values():
        assert len(rep.trust.deductions) == 5
        for d in rep.trust.deductions:
            assert any(ch.isdigit() for ch in d.reason), d


def test_cli_writes_report_json_and_prints_station_name(tmp_path, capsys):
    assert cli.main(["report", "--site", "03451000", "--out", str(tmp_path)]) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("SWANNANOA RIVER AT BILTMORE, NC (03451000): Trusted")
    data = json.loads((tmp_path / "03451000.json").read_text(encoding="utf-8"))
    assert Report.model_validate(data).site_name == "SWANNANOA RIVER AT BILTMORE, NC"


def test_cli_refuses_live_source(capsys):
    assert cli.main(["report", "--site", "03451000", "--source", "live"]) == 2


def test_report_counts_invalid_domain_and_stays_finite():
    from datetime import timedelta

    from driftwatch.core.schemas import Measurement
    from driftwatch.modules.rating_curve import rating
    from tests.test_segmentation import _synthetic_ds

    ds = _synthetic_ds()
    e = rating.fit_rating(ds).e
    last = ds.measurements[-1].time
    low = Measurement(
        site="x",
        field_visit_id="low",
        time=last + timedelta(days=5),
        stage_ft=e - 0.05,
        discharge_cfs=3.0,
        rated="Good",
        weight=3.0,
    )
    ds = ds.model_copy(update={"measurements": [*ds.measurements, low]})
    rep = report.build_report("x", ds=ds)
    assert rep.drift.n_invalid_domain == 1
    assert "1 at or below rating zero" in report.summary_line(rep)
    assert all(d.points == d.points for d in rep.trust.deductions)  # no NaN points


@pytest.mark.parametrize(
    "note, points",
    [
        ("Debris - Moderate", 8.0),
        ("Debris – Moderate", 8.0),  # en dash
        ("Debris — Heavy", 12.0),  # em dash
        ("Vegetation–Light", 3.0),
        ("Debris", 3.0),  # no severity -> light
    ],
)
def test_note_severity_reads_any_dash(note, points):
    assert report.note_severity_points(note) == points


def _helene_ds(with_flood_visit=True):
    """Clean gauge, reference window ends 2024-09-25; optionally one Helene-excluded Poor gauging
    on 2024-09-27 carrying a control-changed note, and nothing after it."""
    from datetime import UTC, date, datetime, timedelta

    import numpy as np

    from driftwatch.core.schemas import Dataset, Measurement
    from driftwatch.modules.rating_curve import pairing

    rng = np.random.default_rng(5)
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    ms = []
    t = t0
    while t.date() <= date(2024, 9, 1):
        h = float(rng.uniform(1.5, 8.0))
        q = 40.0 * (h - 0.5) ** 1.7 * float(np.exp(rng.normal(0, 0.03)))
        ms.append(
            Measurement(
                site="x",
                field_visit_id=t.isoformat(),
                time=t,
                stage_ft=h,
                discharge_cfs=q,
                rated="Good",
                weight=3.0,
                control_condition="Clear",
            )
        )
        t += timedelta(days=60)
    if with_flood_visit:
        ms.append(
            Measurement(
                site="x",
                field_visit_id="helene",
                time=datetime(2024, 9, 27, 18, tzinfo=UTC),
                stage_ft=20.0,
                discharge_cfs=50000.0,
                rated="Poor",
                weight=1.0,
                control_condition="Fill control changed",
                excluded=True,
                exclude_reason=pairing.HELENE_REASON,
            )
        )
    return Dataset(
        site="x",
        source="snapshot",
        fetched_at=datetime(2024, 10, 27, 18, tzinfo=UTC),
        reference_start=t0.date(),
        reference_end=date(2024, 9, 25),
        measurements=ms,
    )


def test_helene_excluded_visit_counts_for_staleness_data_and_notes_only():
    from driftwatch.modules.rating_curve import rating, segmentation

    with_flood, without = _helene_ds(True), _helene_ds(False)
    rel_w, rel_wo = rating.fit_rating(with_flood), rating.fit_rating(without)
    # Out of the fit and the drift test.
    assert (rel_w.a, rel_w.b, rel_w.e) == (rel_wo.a, rel_wo.b, rel_wo.e)
    drift_w, drift_wo = (
        segmentation.drift_test(d, r) for d, r in [(with_flood, rel_w), (without, rel_wo)]
    )
    assert drift_w.n_tested == drift_wo.n_tested and drift_w.n_excluded == 1
    # In for staleness, the 12-month data count, and field notes.
    inp_w = report.trust_inputs(with_flood, rel_w, drift_w, with_flood.fetched_at)
    inp_wo = report.trust_inputs(without, rel_wo, drift_wo, without.fetched_at)
    assert inp_w.days_since_last == pytest.approx(30.0)
    assert inp_wo.days_since_last > 50
    assert inp_w.n_last_year == inp_wo.n_last_year + 1
    assert ("Fill control changed", report.CONTROL_CHANGED_POINTS) in inp_w.field_flags
    assert inp_wo.field_flags == []
    # Recent residual and quality still come from tested measurements only.
    assert "Poor" not in inp_w.recent_rated
    assert inp_w.recent_residual_pct == inp_wo.recent_residual_pct


# --- dh steps 3-4: suggested shift and reference mode -----------------------------------


def _stepped_ds(n_ref=80, n_post=24, step_ft=-0.4, poor_every=6, seed=11):
    """Clean gauge on Q = 40 (H - 0.5)^1.7, one visit every 45 days from 2012. After the
    reference window the channel reads `step_ft` ft of stage shift (USGS sign: fill negative);
    every `poor_every`-th post visit is a wild Poor gauging (+60 % flow)."""
    from datetime import UTC, datetime, timedelta

    import numpy as np

    from driftwatch.core.schemas import Dataset, Measurement
    from driftwatch.modules.rating_curve import pairing

    rng = np.random.default_rng(seed)
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    ms = []
    for i in range(n_ref + n_post):
        h = float(rng.uniform(1.5, 8.0))
        post = i >= n_ref
        poor = post and (i - n_ref) % poor_every == poor_every - 1
        h_eff = h + step_ft if post else h
        q = 40.0 * (h_eff - 0.5) ** 1.7 * float(np.exp(rng.normal(0, 0.03)))
        rated = "Poor" if poor else "Good"
        ms.append(
            Measurement(
                site="x",
                field_visit_id=str(i),
                time=t0 + timedelta(days=45 * i),
                stage_ft=h,
                discharge_cfs=q * (1.6 if poor else 1.0),
                rated=rated,
                weight=pairing.quality_weight(rated),
                control_condition="Clear",
            )
        )
    return (
        Dataset(
            site="x",
            source="snapshot",
            fetched_at=ms[-1].time + timedelta(days=30),
            reference_start=t0.date(),
            reference_end=ms[n_ref - 1].time.date(),
            measurements=ms,
        ),
        ms,
    )


def test_suggested_shift_is_the_weighted_median_over_the_latest_stable_period():
    ds, ms = _stepped_ds()
    rep = report.build_report("x", ds=ds)
    # A constant ft step is a big % error at low stage and a small one at high stage, so the
    # % series may split the post-step record more than once; the latest period is after it.
    start = rep.drift.stable_periods[-1].start
    assert start >= ms[80].time
    since = [m for m in ms if m.time >= start]
    assert rep.suggested_shift_n == sum(1 for m in since if m.rated != "Poor") >= 6
    assert rep.suggested_shift_ft == pytest.approx(-0.4, abs=0.05)
    assert "hydrographer confirms" in rep.suggested_shift_label
    assert "provisional" in rep.suggested_shift_label


def test_suggested_shift_on_a_quiet_gauge_is_near_zero(reports):
    rep = reports["03451000"]
    assert abs(rep.suggested_shift_ft) < 0.05
    assert rep.suggested_shift_n > 15


def test_suggested_shift_has_the_sign_of_the_newport_fill(reports):
    rep = reports["03455000"]
    assert rep.suggested_shift_ft < 0
    assert rep.suggested_shift_n >= 6


def _period(start, end, n):
    from datetime import UTC, datetime

    from driftwatch.core.schemas import StablePeriod

    return StablePeriod(
        start=datetime.fromisoformat(start).replace(tzinfo=UTC),
        end=datetime.fromisoformat(end).replace(tzinfo=UTC),
        n=n,
    )


def test_auto_cuts_a_long_latest_period_before_the_newest_8():
    from datetime import UTC, date, datetime, timedelta

    from driftwatch.modules.rating_curve import pairing

    periods = [_period("2005-01-01", "2011-12-31", 40), _period("2012-01-10", "2026-10-01", 90)]
    times = [datetime(2012, 1, 10, tzinfo=UTC) + timedelta(days=58 * i) for i in range(90)]
    start, end, which = pairing.auto_reference_window(periods, times)
    assert which == "latest" and start == date(2012, 1, 10)
    assert end == times[-8].date() - timedelta(days=1)
    assert sum(1 for t in times if t.date() > end) == 8


def test_auto_keeps_same_day_gaugings_together_in_the_test_set():
    from datetime import UTC, datetime, timedelta

    from driftwatch.modules.rating_curve import pairing

    times = [datetime(2012, 1, 10, 12, tzinfo=UTC) + timedelta(days=58 * i) for i in range(90)]
    times[-9] = times[-8] - timedelta(minutes=40)  # two discharges on one visit
    periods = [_period("2012-01-10", times[-1].isoformat()[:19], 90)]
    _, end, _ = pairing.auto_reference_window(periods, times)
    assert sum(1 for t in times if t.date() > end) == 9


def test_auto_falls_back_to_the_previous_period_when_the_latest_is_short():
    from datetime import UTC, date, datetime, timedelta

    from driftwatch.modules.rating_curve import pairing

    times = [datetime(2024, 10, 28, tzinfo=UTC) + timedelta(days=50 * i) for i in range(30)]
    previous = _period("2004-09-09", "2024-08-19", 80)
    few = _period("2024-10-28", "2026-10-19", 19)  # 19 measurements: < 20
    brief = _period("2025-01-01", "2026-10-19", 30)  # 30 measurements over 1.8 years: < 2
    for latest in (few, brief):
        assert pairing.auto_reference_window([previous, latest], times) == (
            date(2004, 9, 9),
            date(2024, 8, 19),
            "previous",
        )
    assert pairing.auto_reference_window([few], times) is None  # nothing to fall back to
    enough = _period("2024-10-28", "2026-11-01", 20)
    assert pairing.auto_reference_window([previous, enough], times)[2] == "latest"


def test_fixed_is_the_default_and_recorded(reports):
    from driftwatch.modules.rating_curve import pairing

    rep = reports["03459500"]
    assert rep.reference_mode == "fixed"
    assert (rep.reference_start, rep.reference_end) == pairing.reference_window("03459500")
    assert rep.reference_note is None


def test_unknown_reference_mode_is_refused():
    with pytest.raises(ValueError, match="reference_mode"):
        report.build_report("03459500", reference_mode="latest")


def test_auto_short_post_step_period_tests_everything_after_the_previous_one():
    ds, ms = _stepped_ds(n_post=12)  # 10 searched visits, 1.4 years after the step: too short
    rep = report.build_report("x", ds=ds, reference_mode="auto")
    assert rep.reference_mode == "auto"
    assert "previous stable period" in rep.reference_note
    assert rep.reference_end <= ms[79].time.date()
    assert rep.relationship.reference_end == rep.reference_end
    assert rep.holdout_n == 10
    assert report.top_shift(rep.reference_end, rep.drift).time >= ms[80].time


def test_auto_on_a_quiet_gauge_holds_out_the_newest_8():
    ds, ms = _stepped_ds(n_post=0)  # one long stable period, nothing changes
    rep = report.build_report("x", ds=ds, reference_mode="auto")
    assert "latest stable period, cut off" in rep.reference_note
    assert rep.holdout_n == 8
    assert rep.holdout_start == ms[-8].time
    assert rep.trust.band == "Trusted"


def test_holdout_is_recorded_in_both_modes():
    ds, ms = _stepped_ds(n_post=24)  # 4 of the 24 post visits are Poor
    for mode in ("fixed", "auto"):
        rep = report.build_report("x", ds=ds, reference_mode=mode)
        held = [m for m in ms if m.time.date() > rep.reference_end and m.rated != "Poor"]
        assert rep.holdout_n == len(held)
        assert (rep.holdout_start, rep.holdout_end) == (held[0].time, held[-1].time)
    assert report.build_report("x", ds=ds).holdout_n == 20


@pytest.mark.parametrize(
    "site, band",
    [
        ("03459500", "Stale"),
        ("03455000", "Stale"),
        ("03451500", "Stale"),
        ("03451000", "Trusted"),
        ("03463300", "Trusted"),
        ("03479000", "Trusted"),
        ("02085000", "Trusted"),
    ],
)
def test_auto_and_fixed_agree_on_band_and_shift_date(site, band):
    fixed = report.build_report(site)
    auto = report.build_report(site, reference_mode="auto")
    assert fixed.trust.band == auto.trust.band == band
    top_f = report.top_shift(fixed.reference_end, fixed.drift)
    top_a = report.top_shift(auto.reference_end, auto.drift)
    assert (top_f and top_f.time) == (top_a and top_a.time)


def _stored(site):
    data = json.loads((cli.REPORTS_DIR / f"{site}.json").read_text(encoding="utf-8"))
    return Report.model_validate(data)


def test_stored_mills_report_has_a_significant_downward_trend():
    rep = _stored("03446000")
    assert rep.trend is not None and rep.trend.significant
    assert "lower" in rep.trend.text
    assert rep.trend_note and "not a test on new data" in rep.trend_note


def test_stored_hepco_report_has_no_trend():
    """Under 3 years since the Helene shift: trend.fit_trend declines to claim one."""
    rep = _stored("03459500")
    assert rep.trend is None and rep.trend_note is None


def test_build_report_skips_the_trend_by_default(reports):
    for rep in reports.values():
        assert rep.trend is None and rep.trend_note is None
