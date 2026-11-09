"""Train/test evaluation of the rating model. Shared by the Airflow analysis task and the
model_evaluator agent.

The model is the weighted power-law rating Q = a (H - e)^b (rating.fit_power_law). It answers two
separate questions, so it gets two separate scores:

1. Is the model any good? Chronological split of the reference window: fit on the oldest
   (1 - holdout_frac) of reference gaugings, score the newest holdout_frac. The split is by
   time, not random, so the test set is "the future" relative to training, like real use.
2. Has the channel drifted? Score the *same trained model* on every non-excluded gauging after
   the reference window. A healthy rating scores about the same here as on the holdout; a drifted
   one doesn't. Using one model for both scores keeps drift_ratio an apples-to-apples ratio.

This is model validation, separate from the drift test in report.py: that test keeps b and e fixed
from the base fit and slides a (CLAUDE.md non-negotiable), and nothing here feeds it.

Metrics, all on discharge:
  MdAPE        median absolute % error |Q_meas - Q_hat| / Q_hat
  within_10pct share of gaugings within +-10% of the rating (the "accuracy" figure)
  bias_pct     median signed % error (positive = river carries more than the rating says)

Baseline: plain log-log least squares, Q = c H^d (no zero-flow offset, no weights). It is the
simplest curve a hydrologist would fit, so the power law should beat it on the holdout.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from driftwatch.core.schemas import Dataset, Measurement, Relationship
from driftwatch.modules.rating_curve import rating

TOLERANCE_PCT = 10.0
MIN_TRAIN = 10
MIN_TEST = 5


def _arrays(ms: list[Measurement]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    return (
        np.array([m.stage_ft for m in ms], dtype=float),
        np.array([m.discharge_cfs for m in ms], dtype=float),
        np.array([m.weight for m in ms], dtype=float),
    )


def scores(pct_err: np.ndarray) -> dict[str, Any]:
    """MdAPE / within-tolerance / bias for an array of signed % errors (NaN = out of domain)."""
    e = np.asarray(pct_err, dtype=float)
    ok = e[np.isfinite(e)]
    if ok.size == 0:
        return {"n": 0, "mdape_pct": None, "within_10pct": None, "bias_pct": None}
    return {
        "n": int(ok.size),
        "mdape_pct": round(float(np.median(np.abs(ok))), 2),
        "within_10pct": round(float(np.mean(np.abs(ok) <= TOLERANCE_PCT)), 3),
        "bias_pct": round(float(np.median(ok)), 2),
    }


def _train_power_law(train: list[Measurement]) -> Relationship:
    a, b, e, rmse = rating.fit_power_law(*_arrays(train))
    return Relationship(
        a=a,
        b=b,
        e=e,
        reference_start=train[0].time.date(),
        reference_end=train[-1].time.date(),
        n=len(train),
        rmse_log=rmse,
    )


def _errors(rel: Relationship, ms: list[Measurement]) -> np.ndarray:
    if not ms:
        return np.array([])
    h, q, _ = _arrays(ms)
    return rating.residual_pct(rel, h, q)


def _loglog_errors(train: list[Measurement], test: list[Measurement]) -> np.ndarray:
    h, q, _ = _arrays(train)
    d, lnc = np.polyfit(np.log(h), np.log(q), 1)
    ht, qt, _ = _arrays(test)
    qhat = np.exp(lnc) * ht**d
    return (qt - qhat) / qhat * 100.0


def evaluate_rating(ds: Dataset, holdout_frac: float = 0.2) -> dict[str, Any]:
    """Holdout + post-reference scores for one gauge. JSON-safe."""
    ref = sorted(rating.reference_measurements(ds), key=lambda m: m.time)
    n_test = max(MIN_TEST, round(len(ref) * holdout_frac))
    out: dict[str, Any] = {
        "site": ds.site,
        "site_name": ds.site_name,
        "source": ds.source,
        "model": "weighted power law Q = a(H - e)^b",
        "baseline": "log-log least squares Q = c H^d",
        "n_reference": len(ref),
        "holdout_frac": holdout_frac,
    }
    if len(ref) - n_test < MIN_TRAIN:
        out["error"] = f"too few reference gaugings to split ({len(ref)})"
        return out
    train, test = ref[:-n_test], ref[-n_test:]
    rel = _train_power_law(train)
    out["split_time"] = test[0].time.isoformat()
    out["n_train"], out["n_test"] = len(train), len(test)
    out["holdout"] = scores(_errors(rel, test))
    out["baseline_holdout"] = scores(_loglog_errors(train, test))
    out["train_params"] = {"a": round(rel.a, 4), "b": round(rel.b, 4), "e": round(rel.e, 4)}

    post = [m for m in ds.measurements if not m.excluded and m.time.date() > ds.reference_end]
    out["post_reference"] = scores(_errors(rel, post))
    ho, pr = out["holdout"]["mdape_pct"], out["post_reference"]["mdape_pct"]
    out["beats_baseline"] = (
        ho is not None
        and out["baseline_holdout"]["mdape_pct"] is not None
        and ho <= out["baseline_holdout"]["mdape_pct"]
    )
    # drift ratio: how much worse the rating does after the reference window than on its own
    # holdout. ~1 = still fits; >> 1 = the channel moved.
    out["drift_ratio"] = round(pr / ho, 2) if ho and pr is not None else None
    return out
