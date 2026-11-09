"""Recursive segmentation: synthetic step, and the three calibration gauges from the plan."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from driftwatch.core.schemas import Dataset, Measurement
from driftwatch.modules.rating_curve import pairing, rating, segmentation

HELENE = datetime(2024, 9, 26, tzinfo=UTC)


def _post_helene_shifts(site):
    ds = pairing.load_dataset(site)
    drift = segmentation.drift_test(ds, rating.fit_rating(ds))
    return drift, [s for s in drift.shifts if s.time >= HELENE]


def test_change_points_find_a_clean_step_and_ignore_noise():
    rng = np.random.default_rng(1)
    quiet = rng.normal(0, 1, 80)
    assert segmentation.change_points(quiet) == []
    step = np.concatenate([rng.normal(0, 1, 60), rng.normal(-8, 1, 20)])
    assert segmentation.change_points(step) == [60]


def test_synthetic_fill_shift_is_negative_with_size():
    rng = np.random.default_rng(2)
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    ms = []
    for i in range(100):
        h = float(rng.uniform(1.5, 8.0))
        factor = 0.7 if i >= 80 else 1.0  # 30 % less flow at the same stage after point 80
        q = 40.0 * (h - 0.5) ** 1.7 * factor * float(np.exp(rng.normal(0, 0.03)))
        ms.append(
            Measurement(
                site="x",
                field_visit_id=str(i),
                time=t0 + timedelta(days=60 * i),
                stage_ft=h,
                discharge_cfs=q,
                rated="Good",
                weight=3.0,
            )
        )
    ds = Dataset(
        site="x",
        source="snapshot",
        reference_start=t0.date(),
        reference_end=ms[79].time.date(),
        measurements=ms,
    )
    drift = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert len(drift.shifts) == 1
    s = drift.shifts[0]
    assert s.time == ms[80].time
    assert s.direction == "negative"
    assert s.size_pct == pytest.approx(-30, abs=5)
    assert s.size_ft < 0
    assert s.n_after == 20 and s.confidence > 0.99
    assert [p.n for p in drift.stable_periods] == [80, 20]


@pytest.mark.parametrize("site", ["02085000", "03451000"])
def test_controls_have_no_shift_after_helene(site):
    _, post = _post_helene_shifts(site)
    assert post == []


def test_newport_shifts_negative_after_helene():
    drift, post = _post_helene_shifts("03455000")
    assert len(post) == 1
    assert post[0].direction == "negative" and post[0].size_pct < -20
    assert drift.n_excluded >= 1  # the Sept 27-28 Poor flood gaugings are held out


def _synthetic_ds(n_ref=80, n_post=20, factor=1.0, seed=3):
    rng = np.random.default_rng(seed)
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    ms = []
    for i in range(n_ref + n_post):
        h = float(rng.uniform(1.5, 8.0))
        f = factor if i >= n_ref else 1.0
        q = 40.0 * (h - 0.5) ** 1.7 * f * float(np.exp(rng.normal(0, 0.03)))
        ms.append(
            Measurement(
                site="x",
                field_visit_id=str(i),
                time=t0 + timedelta(days=60 * i),
                stage_ft=h,
                discharge_cfs=q,
                rated="Good",
                weight=3.0,
            )
        )
    return Dataset(
        site="x",
        source="snapshot",
        fetched_at=ms[-1].time + timedelta(days=30),
        reference_start=t0.date(),
        reference_end=ms[n_ref - 1].time.date(),
        measurements=ms,
    )


def test_stage_at_or_below_e_is_invalid_domain_left_out_and_counted():
    ds = _synthetic_ds()
    rel = rating.fit_rating(ds)
    last = ds.measurements[-1].time
    low = [
        Measurement(
            site="x",
            field_visit_id=f"low{k}",
            time=last + timedelta(days=10 * (k + 1)),
            stage_ft=rel.e - 0.1 * k,  # at e, then below it
            discharge_cfs=3.0,
            rated="Good",
            weight=3.0,
        )
        for k in range(3)
    ]
    ds = ds.model_copy(update={"measurements": ds.measurements + low})
    drift = segmentation.drift_test(ds, rel)
    assert drift.n_invalid_domain == 3
    assert drift.n_tested == 100
    assert all(np.isfinite(s.size_pct) and np.isfinite(s.size_ft) for s in drift.shifts)
    assert all(np.isfinite(p.median_residual_pct) for p in drift.stable_periods)
    rows = rating.residual_table(rel, ds.measurements)
    assert [r["invalid_domain"] for r in rows[-3:]] == [True, True, True]
    assert not any(r["invalid_domain"] for r in rows[:-3])


def test_n_after_counts_every_measurement_since_the_shift():
    """Two steps (down 30 %, then back up): the first shift's n_after spans both later segments."""
    rng = np.random.default_rng(4)
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    ms = []
    for i in range(120):
        h = float(rng.uniform(1.5, 8.0))
        factor = 0.7 if 60 <= i < 90 else 1.0
        q = 40.0 * (h - 0.5) ** 1.7 * factor * float(np.exp(rng.normal(0, 0.03)))
        ms.append(
            Measurement(
                site="x",
                field_visit_id=str(i),
                time=t0 + timedelta(days=60 * i),
                stage_ft=h,
                discharge_cfs=q,
                rated="Good",
                weight=3.0,
            )
        )
    ds = Dataset(
        site="x",
        source="snapshot",
        reference_start=t0.date(),
        reference_end=ms[59].time.date(),
        measurements=ms,
    )
    drift = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert [s.time for s in drift.shifts] == [ms[60].time, ms[90].time]
    assert [s.direction for s in drift.shifts] == ["negative", "positive"]
    assert [s.n_after for s in drift.shifts] == [60, 30]


def test_null_eno_resampled_residuals_give_no_shift_after_reference():
    """Synthetic null: 20 visits after Eno's reference window, each a reference stage with a
    reference-window residual drawn at random (seed fixed at 0, chosen before running). No step
    is injected, so nothing should fire after the window. Known limit (decision log 2026-11-07):
    across seeds this null fires about 4-34 % of the time as the post-window series grows from
    10 to 40 visits, so a single seed passing is a smoke test, not a false-alarm rate.
    Resampled from the search series (Poor left out, dh step 2), the population the search sees;
    rates then 4 / 18 / 40 % at 10 / 20 / 40 visits (decision log, dh 2)."""
    ds = pairing.load_dataset("02085000")
    rel = rating.fit_rating(ds)
    ref = [
        m for m in segmentation.search_measurements(ds, rel) if m.time.date() <= ds.reference_end
    ]
    h_ref = np.array([m.stage_ft for m in ref])
    log_r = np.log(np.array([m.discharge_cfs for m in ref]) / rating.predict_q(rel, h_ref))
    rng = np.random.default_rng(0)
    t = ref[-1].time
    post = []
    for i in range(20):
        j, k = rng.integers(len(ref), size=2)
        t += timedelta(days=45)
        q = float(rating.predict_q(rel, h_ref[j]) * np.exp(log_r[k]))
        post.append(
            ref[j].model_copy(update={"time": t, "discharge_cfs": q, "field_visit_id": f"null{i}"})
        )
    pre = [m for m in ds.measurements if m.time.date() <= ds.reference_end]
    drift = segmentation.drift_test(ds.model_copy(update={"measurements": pre + post}), rel)
    assert [s for s in drift.shifts if s.time.date() > ds.reference_end] == []


# --- dh step 1: two residual series -------------------------------------------------------


def _shift_ds(after, n_ref=80, n_post=24, seed=5, rated="Good"):
    """Synthetic gauge on Q = 40 (H - 0.5)^1.7. `after(h)` maps a post-reference stage to the
    stage the old rating should have been read at (the channel change)."""
    rng = np.random.default_rng(seed)
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    ms = []
    for i in range(n_ref + n_post):
        h = float(rng.uniform(1.5, 8.0))
        h_eff = after(h) if i >= n_ref else h
        q = 40.0 * (h_eff - 0.5) ** 1.7 * float(np.exp(rng.normal(0, 0.03)))
        r = rated(i) if callable(rated) else rated
        ms.append(
            Measurement(
                site="x",
                field_visit_id=str(i),
                time=t0 + timedelta(days=45 * i),
                stage_ft=h,
                discharge_cfs=q,
                rated=r,
                weight=pairing.quality_weight(r),
            )
        )
    ds = Dataset(
        site="x",
        source="snapshot",
        reference_start=t0.date(),
        reference_end=ms[n_ref - 1].time.date(),
        measurements=ms,
    )
    return ds, ms


def test_low_control_fill_shows_in_ft_at_low_flows():
    # Fill on the low-water control: 0.6 ft less effective stage at 1.5 ft, fading to 0 by 8 ft.
    ds, ms = _shift_ds(lambda h: h - 0.6 * max(0.0, 1 - (h - 1.5) / 6.5))
    drift = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert [s.time for s in drift.shifts_ft] == [ms[80].time]
    assert drift.shifts_ft[0].size_ft < 0
    assert drift.low_flow_concentrated is True
    assert drift.larger_step_series in ("pct", "ft")


def test_uniform_percent_slide_is_not_low_flow_concentrated():
    # 30 % less flow at every stage: in ft that step is biggest at high flows.
    ds, ms = _shift_ds(lambda h: 0.5 + (h - 0.5) * 0.7 ** (1 / 1.7))
    drift = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert [s.time for s in drift.shifts] == [ms[80].time]
    assert drift.low_flow_concentrated is False


def test_larger_step_series_matches_the_standardized_steps():
    for site in ("03459500", "03455000", "03451500"):
        ds = pairing.load_dataset(site)
        d = segmentation.drift_test(ds, rating.fit_rating(ds))
        want = "ft" if (d.step_ft_sigma or 0) > (d.step_pct_sigma or 0) else "pct"
        assert d.larger_step_series == want


def test_no_post_reference_shift_means_no_larger_series():
    ds = pairing.load_dataset("03451000")
    d = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert d.larger_step_series is None and d.low_flow_concentrated is False


def test_newport_step_is_larger_in_ft_and_at_low_flows():
    ds = pairing.load_dataset("03455000")
    d = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert d.larger_step_series == "ft"
    assert d.low_flow_concentrated is True


# --- dh step 2: quality weighting ---------------------------------------------------------


def test_weighted_median():
    assert segmentation.weighted_median([1, 2, 3], [1, 1, 1]) == 2
    assert segmentation.weighted_median([1, 2, 3, 4], [1, 1, 1, 1]) == 2.5
    assert segmentation.weighted_median([0, 10], [4, 1]) == 0  # Excellent outweighs Poor
    assert segmentation.weighted_median([0, 10, 11], [1, 1, 3]) == 11
    assert np.isnan(segmentation.weighted_median([], []))


def test_poor_gaugings_are_left_out_of_the_search_but_counted():
    # The last 10 visits read 40 % low, but every one is rated Poor: no shift, still counted.
    ds, _ = _shift_ds(
        lambda h: 0.5 + (h - 0.5) * 0.6 ** (1 / 1.7),
        n_post=10,
        rated=lambda i: "Poor" if i >= 80 else "Good",
    )
    drift = segmentation.drift_test(ds, rating.fit_rating(ds))
    assert drift.shifts == [] and drift.shifts_ft == []
    assert drift.n_tested == 90
    assert drift.n_poor_unsearched == 10
    # The same visits rated Good do make a shift.
    ds2, _ = _shift_ds(lambda h: 0.5 + (h - 0.5) * 0.6 ** (1 / 1.7), n_post=10)
    assert segmentation.drift_test(ds2, rating.fit_rating(ds2)).shifts


def test_shift_size_is_quality_weighted():
    # After the shift: Excellent visits read 30 % low, Fair ones 10 % low (half and half).
    # The weighted median (4 vs 2) lands on the Excellent value; a plain median would not.
    t0 = datetime(2012, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(7)
    ms = []
    for i in range(110):
        h = float(rng.uniform(1.5, 8.0))
        rated, factor = "Good", 1.0
        if i >= 80:
            rated = "Fair" if i % 2 else "Excellent"
            factor = 0.9 if i % 2 else 0.7
        q = 40.0 * (h - 0.5) ** 1.7 * factor * float(np.exp(rng.normal(0, 0.03)))
        ms.append(
            Measurement(
                site="x",
                field_visit_id=str(i),
                time=t0 + timedelta(days=45 * i),
                stage_ft=h,
                discharge_cfs=q,
                rated=rated,
                weight=pairing.quality_weight(rated),
            )
        )
    ds = Dataset(
        site="x",
        source="snapshot",
        reference_start=t0.date(),
        reference_end=ms[79].time.date(),
        measurements=ms,
    )
    rel = rating.fit_rating(ds)
    pct = rating.residual_pct(
        rel, [m.stage_ft for m in ms[80:]], [m.discharge_cfs for m in ms[80:]]
    )
    assert float(np.median(pct)) == pytest.approx(-20, abs=3)  # what a plain median says
    shifts = segmentation.drift_test(ds, rel).shifts
    assert [s.time for s in shifts] == [ms[80].time]
    assert shifts[0].size_pct == pytest.approx(-30, abs=4)


# --- dh round 2: magnitude gate -------------------------------------------------------------


def test_gate_is_max_of_10_and_1p5_reference_mdape():
    ds = pairing.load_dataset("02085000")
    rel = rating.fit_rating(ds)
    mdape = rating.mdape(rel, rating.reference_measurements(ds))
    assert segmentation.shift_gate_pct(ds, rel) == pytest.approx(max(10.0, 1.5 * mdape))
    assert segmentation.shift_gate_pct(ds, rel) > 10  # Eno's MdAPE is about 8 %
    ds2 = pairing.load_dataset("03451000")
    assert segmentation.shift_gate_pct(ds2, rating.fit_rating(ds2)) == 10.0


def test_small_step_is_found_but_gated_out():
    # A 6 % step (3 % noise): PELT finds it, the 10 % gate drops it.
    ds, ms = _shift_ds(lambda h: 0.5 + (h - 0.5) * 0.94 ** (1 / 1.7), seed=8)
    ds = ds.model_copy(
        update={
            "measurements": [
                m.model_copy(update={"discharge_cfs": m.discharge_cfs**1.0}) for m in ms
            ]
        }
    )
    rel = rating.fit_rating(ds)
    ungated = segmentation.drift_test(ds, rel, min_shift_pct=0)
    gated = segmentation.drift_test(ds, rel)
    assert gated.min_shift_pct == 10.0
    assert [round(s.size_pct) for s in ungated.shifts] == [-6]
    assert gated.shifts == [] and gated.n_gated == 1
    assert all(abs(s.size_pct) > 10 for s in gated.shifts_ft)


def test_gate_merges_and_recomputes_neighbours():
    pct = np.array([0.0] * 10 + [5.0] * 10 + [40.0] * 10)
    w = np.ones(30)
    assert segmentation.gate_change_points([10, 20], 30, pct, w, 10.0) == [20]
    assert segmentation.gate_change_points([10, 20], 30, pct, w, 50.0) == []
    assert segmentation.gate_change_points([10, 20], 30, pct, w, 0.0) == [10, 20]
