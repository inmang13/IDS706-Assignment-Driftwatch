"""Base rating fit: synthetic recovery, sign conventions, and the Eno accuracy gate."""

from datetime import date

import numpy as np
import pytest

from driftwatch.core.schemas import Relationship
from driftwatch.modules.rating_curve import pairing, rating


def _rel(a=50.0, b=1.8, e=0.5):
    return Relationship(
        a=a, b=b, e=e, reference_start=date(2012, 1, 1), reference_end=date(2024, 9, 25), n=0
    )


def test_fit_recovers_synthetic_curve():
    rng = np.random.default_rng(0)
    h = np.linspace(1.0, 12.0, 80)
    q = 50.0 * (h - 0.5) ** 1.8 * np.exp(rng.normal(0, 0.02, h.size))
    _a, b, e, rmse = rating.fit_power_law(h, q, np.ones_like(h))
    assert b == pytest.approx(1.8, abs=0.1)
    assert e == pytest.approx(0.5, abs=0.15)
    assert e < h.min()
    assert rmse < 0.05


def test_predict_h_inverts_predict_q():
    rel = _rel()
    h = np.array([1.0, 3.0, 9.0])
    assert rating.predict_h(rel, rating.predict_q(rel, h)) == pytest.approx(h)


def test_scour_gives_positive_residual_and_positive_stage_shift():
    rel = _rel()
    h = 4.0
    q_more = 1.2 * float(rating.predict_q(rel, h))  # channel carries more flow than rated
    assert float(rating.residual_pct(rel, h, q_more)) == pytest.approx(20.0)
    assert float(rating.stage_shift_ft(rel, h, q_more)) > 0
    q_less = 0.8 * float(rating.predict_q(rel, h))  # fill
    assert float(rating.residual_pct(rel, h, q_less)) < 0
    assert float(rating.stage_shift_ft(rel, h, q_less)) < 0


def test_too_few_points_raises():
    with pytest.raises(rating.FitError):
        rating.fit_power_law(np.array([1.0, 2.0]), np.array([1.0, 2.0]), np.ones(2))


def test_eno_reference_mdape_under_10_pct():
    ds = pairing.load_dataset("02085000")
    rel = rating.fit_rating(ds)
    ref = rating.reference_measurements(ds)
    assert rel.n == len(ref) > 50
    assert rel.e < min(m.stage_ft for m in ref)
    assert rating.mdape(rel, ref) < 10.0


def test_stage_at_or_below_e_is_nan_never_zero_or_complex():
    rel = _rel(e=0.5)
    h = np.array([0.2, 0.5, 2.0])
    q = np.array([5.0, 5.0, 100.0])
    assert list(rating.in_domain(rel, h)) == [False, False, True]
    qhat = rating.predict_q(rel, h)
    assert np.isnan(qhat[:2]).all() and qhat[2] > 0
    assert np.isnan(rating.residual_pct(rel, h, q)[:2]).all()
    assert np.isnan(rating.stage_shift_ft(rel, h, q)[:2]).all()
    assert np.isnan(rel.discharge(0.2)) and isinstance(rel.discharge(0.2), float)
    assert rel.discharge(2.0) == pytest.approx(50.0 * 1.5**1.8)
