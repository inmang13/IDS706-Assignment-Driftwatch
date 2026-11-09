import pytest

from driftwatch.core import trust


def _inputs(**kw):
    base = {
        "recent_residual_pct": [1.0, -2.0, 0.5, 2.0, -1.0, 0.0],
        "normal_scatter_pct": 4.0,
        "days_since_last": 30,
        "recent_rated": ["Good"] * 6,
        "field_flags": [],
        "n_last_year": 6,
    }
    base.update(kw)
    return trust.TrustInputs(**base)


def test_clean_gauge_scores_100_with_all_five_deductions_listed():
    ts = trust.score(_inputs())
    assert ts.score == 100 and ts.band == "Trusted"
    assert [d.name for d in ts.deductions] == [
        "residual",
        "staleness",
        "quality",
        "field_notes",
        "insufficient_data",
    ]
    assert all(d.reason for d in ts.deductions)


def test_large_negative_residual_hits_cap_and_reason_has_the_number():
    ts = trust.score(_inputs(recent_residual_pct=[-40.0] * 6))
    d = ts.deductions[0]
    assert d.points == trust.RESIDUAL_MAX
    assert "40.0 %" in d.reason and "less water" in d.reason
    assert ts.band == "Watch"


def test_residual_inside_normal_scatter_is_free_and_excess_is_linear():
    assert trust.residual_deduction([3.0] * 5, 4.0).points == 0
    assert trust.residual_deduction([9.0] * 5, 4.0).points == pytest.approx(10.0)


def test_staleness_grace_then_linear_then_cap():
    assert trust.staleness_deduction(60).points == 0
    assert trust.staleness_deduction(227.5).points == pytest.approx(10.0)
    assert trust.staleness_deduction(1000).points == trust.STALE_MAX
    assert trust.staleness_deduction(None).points == trust.STALE_MAX


def test_quality_and_notes_and_data():
    q = trust.quality_deduction(["Poor", "Poor", "Good", "Good"])
    assert q.points == pytest.approx(7.5) and "2 Poor" in q.reason
    n = trust.notes_deduction([("Fill control changed", 15), ("Debris - Light", 3)])
    assert n.points == trust.NOTES_MAX and "Fill control changed" in n.reason
    assert trust.data_deduction(1).points == pytest.approx(7.5)
    assert trust.data_deduction(0).points == trust.DATA_MAX


def test_drifted_gauge_with_flag_is_stale():
    ts = trust.score(
        _inputs(
            recent_residual_pct=[-35.0] * 8,
            recent_rated=["Poor"] * 4 + ["Fair"] * 4,
            field_flags=[("Fill control changed", 15)],
        )
    )
    assert ts.band == "Stale"
    assert ts.score == pytest.approx(100 - trust.RESIDUAL_MAX - 10 - 15)
