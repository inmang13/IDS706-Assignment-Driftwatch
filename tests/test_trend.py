"""Slow-drift trend on the latest stable segment (driftwatch/modules/rating_curve/trend.py)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from driftwatch.modules.rating_curve import pairing, rating, segmentation, trend

T0 = datetime(2013, 3, 1, tzinfo=UTC)


def _series(n, years, slope, sd, seed):
    rng = np.random.default_rng(seed)
    t_years = np.sort(rng.uniform(0, years, n))
    times = [T0 + timedelta(days=float(x) * 365.25) for x in t_years]
    return times, slope * t_years + rng.normal(0, sd, n)


def test_known_downward_trend_is_significant_and_close():
    times, r = _series(60, 12.0, -1.5, 5.0, seed=3)
    res = trend.fit_trend(times, r)
    assert res is not None and res.significant
    assert abs(res.slope_pct_per_year - (-1.5)) <= 0.4
    assert res.ci_low < -1.5 < res.ci_high
    assert res.n == 60 and res.span_years > 10
    assert res.text.startswith("Readings have drifted about 1.") and "lower" in res.text
    assert "since 2013 (60 measurements)." in res.text


def test_upward_trend_says_higher():
    times, r = _series(40, 8.0, 2.0, 3.0, seed=5)
    res = trend.fit_trend(times, r)
    assert res.significant and "higher" in res.text and "lower" not in res.text


def test_flat_noise_false_positive_rate_at_most_3_pct():
    # 20 points over 5 years keeps 200 full fits (2,000 resamples each) quick on the Orange Pi.
    hits = 0
    for seed in range(200):
        times, r = _series(20, 5.0, 0.0, 8.0, seed=1000 + seed)
        res = trend.fit_trend(times, r)
        hits += bool(res and res.significant)
    assert hits / 200 <= 0.03


def test_too_few_points_or_too_short_returns_none():
    times, r = _series(11, 10.0, -2.0, 1.0, seed=1)
    assert trend.fit_trend(times, r) is None
    times, r = _series(30, 2.5, -2.0, 1.0, seed=1)
    assert trend.fit_trend(times, r) is None


def test_same_seed_same_output():
    times, r = _series(40, 9.0, -1.0, 6.0, seed=11)
    w = np.random.default_rng(0).choice([1.0, 2.0, 3.0, 4.0], size=40)
    assert trend.fit_trend(times, r, w) == trend.fit_trend(times, r, w)


def test_weights_pull_the_slope_toward_heavy_points():
    times, r = _series(40, 10.0, 0.0, 0.5, seed=2)
    t_years = np.array([(t - times[0]).days / 365.25 for t in times])
    noisy = r.copy()
    noisy[::2] += -3.0 * t_years[::2]  # half the points trend down hard, low weight
    w = np.where(np.arange(40) % 2 == 0, 0.1, 4.0)
    weighted = trend.fit_trend(times, noisy, w).slope_pct_per_year
    unweighted = trend.fit_trend(times, noisy).slope_pct_per_year
    assert abs(weighted) < abs(unweighted)


def test_mann_kendall_p_matches_known_extremes():
    t = np.arange(20.0)
    assert trend.mann_kendall_p(t, t) < 1e-6
    assert trend.mann_kendall_p(t, np.zeros(20)) == 1.0


@pytest.mark.parametrize("site", ["03459500", "03455000"])
def test_short_post_shift_windows_return_none(site):
    """Hepco and Newport have < 3 years since their Helene shift: no trend is claimed."""
    ds = pairing.load_dataset(site)
    rel = rating.fit_rating(ds)
    drift = segmentation.drift_test(ds, rel)
    assert trend.site_trend(ds, rel, drift) is None
    ms = trend.trend_measurements(ds, rel, drift)
    assert ms and ms[0].time >= drift.shifts[-1].time
