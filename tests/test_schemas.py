from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from driftwatch.core.schemas import (
    Deduction,
    DriftResult,
    Measurement,
    Relationship,
    Report,
    Shift,
    TraceEvent,
    TrustScore,
)


def test_trust_score_glass_box_arithmetic():
    ts = TrustScore.from_deductions(
        [
            Deduction(name="recent_residual", points=35, reason="median residual -43%"),
            Deduction(name="staleness", points=20, reason="no measurement in 400 days"),
        ]
    )
    assert ts.score == 45 and ts.band == "Stale"
    assert TrustScore.from_deductions([]).band == "Trusted"
    assert (
        TrustScore.from_deductions([Deduction(name="x", points=20, reason="r")]).band == "Trusted"
    )
    assert TrustScore.from_deductions([Deduction(name="x", points=21, reason="r")]).band == "Watch"
    assert TrustScore.from_deductions([Deduction(name="x", points=150, reason="r")]).score == 0


def test_trust_score_rejects_inconsistent_values():
    with pytest.raises(ValidationError):
        TrustScore(
            score=90, band="Trusted", deductions=[Deduction(name="x", points=30, reason="r")]
        )
    with pytest.raises(ValidationError):
        TrustScore(
            score=60, band="Trusted", deductions=[Deduction(name="x", points=40, reason="r")]
        )


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        Measurement(
            site="s", field_visit_id="v", time=datetime(2024, 1, 1), stage_ft=1, discharge_cfs=1
        )


def test_report_json_round_trip():
    t = datetime(2024, 10, 15, 14, 0, tzinfo=UTC)
    rep = Report(
        site="03455000",
        generated_at=t,
        source="snapshot",
        relationship=Relationship(
            a=10.0,
            b=2.0,
            e=1.0,
            reference_start=date(2012, 1, 1),
            reference_end=date(2024, 9, 25),
            n=80,
        ),
        drift=DriftResult(
            site="03455000",
            shifts=[
                Shift(
                    time=t,
                    size_pct=-43,
                    size_ft=0.8,
                    direction="negative",
                    n_after=17,
                    confidence=0.9,
                )
            ],
        ),
        trust=TrustScore.from_deductions(
            [Deduction(name="recent_residual", points=40, reason="r")]
        ),
    )
    assert Report.model_validate_json(rep.model_dump_json()) == rep
    assert rep.relationship.discharge(3.0) == pytest.approx(40.0)
    ev = TraceEvent(run_id="r1", site="03455000", seq=0, ts=t, node="triage", status="started")
    assert TraceEvent.model_validate_json(ev.model_dump_json()) == ev


def test_shift_direction_must_match_sign():
    t = datetime(2024, 10, 15, tzinfo=UTC)
    with pytest.raises(ValidationError):
        Shift(time=t, size_pct=-30, size_ft=0.5, direction="positive", n_after=5, confidence=0.5)
    with pytest.raises(ValidationError):
        Shift(
            time=datetime(2024, 10, 15),
            size_pct=30,
            size_ft=0.5,
            direction="positive",
            n_after=5,
            confidence=0.5,
        )
