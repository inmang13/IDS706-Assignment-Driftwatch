"""Pairing rules on a hand-built snapshot (no network, no real data needed)."""

from datetime import UTC, datetime, timedelta

import pytest

from driftwatch.modules.rating_curve import pairing


def _row(visit, time, code, value, reading_type, rated="Good", cc="Clear"):
    return {
        "type": "Feature",
        "properties": {
            "field_visit_id": visit,
            "time": time,
            "parameter_code": code,
            "reading_type": reading_type,
            "value": value,
            "unit_of_measure": "ft" if code == "00065" else "ft^3/s",
            "measurement_rated": rated,
            "control_condition": cc,
            "approval_status": "Approved",
        },
    }


def _stage(visit, time, value):
    return _row(visit, time, "00065", value, "MeanGageHeight")


def _q(visit, time, value, rated="Good"):
    return _row(visit, time, "00060", value, "Discharge", rated=rated)


def _snapshot(rows):
    return {
        "site": "99999999",
        "fetched_at": "2026-11-01T00:00:00Z",
        "api_base": "test",
        "collections": {
            "field-measurements": rows,
            "channel-measurements": [],
            "monitoring-locations": [
                {"properties": {"monitoring_location_name": "TEST RIVER NEAR NOWHERE"}}
            ],
        },
    }


def test_two_discharges_in_one_visit_pair_with_their_own_stage():
    rows = [
        _stage("v1", "2020-05-01T14:00:00+00:00", "2.10"),
        _stage("v1", "2020-05-01T16:00:00+00:00", "2.50"),
        _row("v1", "2020-05-01T14:00:00+00:00", "00065", "9.99", "ReferencePrimary"),
        _q("v1", "2020-05-01T14:00:00+00:00", "100", rated="Excellent"),
        _q("v1", "2020-05-01T16:00:00+00:00", "150", rated="Fair"),
    ]
    ms = pairing.pair_measurements(_snapshot(rows))
    assert [(m.stage_ft, m.discharge_cfs) for m in ms] == [(2.10, 100.0), (2.50, 150.0)]
    assert [m.weight for m in ms] == [4.0, 2.0]
    assert all(m.pairing == "exact" for m in ms)
    assert ms[0].time == datetime(2020, 5, 1, 14, tzinfo=UTC)


def test_exact_match_only_and_drops_are_counted(caplog):
    rows = [
        _stage("v1", "2020-05-01T14:00:00+00:00", "2.0"),
        _q("v1", "2020-05-01T14:00:00+00:00", "100"),  # exact -> paired
        _q("v1", "2020-05-01T14:01:00+00:00", "110"),  # 1 min off -> dropped (no fallback)
        _stage("v2", "2020-06-01T10:00:00+00:00", "3.0"),
        _q("v2", "2020-06-01T10:00:00Z", "200"),  # same instant, other spelling -> paired
        _q("v3", "2020-07-01T10:00:00+00:00", "300"),  # no stage in visit -> dropped
        _stage("v4", "2020-08-01T10:00:00+00:00", "1.0"),  # stage in another visit
        _q("v5", "2020-08-01T10:00:00+00:00", "400"),  # same time, other visit -> dropped
        _stage("v6", "2020-09-01T10:00:00+00:00", "4.0"),
        _stage("v6", "2020-09-01T10:00:00+00:00", "4.5"),  # disagreeing duplicate
        _q("v6", "2020-09-01T10:00:00+00:00", "500"),  # ambiguous -> dropped
        _stage("v7", "2020-10-01T10:00:00+00:00", "5.0"),
        _stage("v7", "2020-10-01T10:00:00+00:00", "5.0"),  # identical duplicate is fine
        _q("v7", "2020-10-01T10:00:00+00:00", "600"),
    ]
    with caplog.at_level("INFO", logger=pairing.__name__):
        ds = pairing.build_dataset(_snapshot(rows))
    assert [m.discharge_cfs for m in ds.measurements] == [100.0, 200.0, 600.0]
    assert all(m.pairing == "exact" for m in ds.measurements)
    assert ds.metadata["pairing_dropped"] == {
        "no_exact_stage": 3,
        "ambiguous_stage": 1,
        "bad_value": 0,
    }
    assert "dropped 4" in caplog.text


def test_blank_and_non_positive_values_dropped_and_weights_default():
    rows = [
        _stage("v1", "2020-05-01T14:00:00+00:00", ""),
        _q("v1", "2020-05-01T14:00:00+00:00", "100"),
        _stage("v2", "2020-05-02T14:00:00+00:00", "2.0"),
        _q("v2", "2020-05-02T14:00:00+00:00", "0"),
        _stage("v3", "2020-05-03T14:00:00+00:00", "2.0"),
        _q("v3", "2020-05-03T14:00:00+00:00", "50", rated="Unspecified"),
    ]
    ms = pairing.pair_measurements(_snapshot(rows))
    assert len(ms) == 1
    assert ms[0].weight == 1.5 and ms[0].rated == "Unspecified"


def test_helene_poor_measurements_marked_excluded_but_kept():
    rows = [
        _stage("v1", "2024-09-27T18:00:00+00:00", "20.0"),
        _q("v1", "2024-09-27T18:00:00+00:00", "50000", rated="Poor"),
        _stage("v2", "2024-09-27T19:00:00+00:00", "19.0"),
        _q("v2", "2024-09-27T19:00:00+00:00", "40000", rated="Good"),
    ]
    ms = pairing.pair_measurements(_snapshot(rows))
    assert [m.excluded for m in ms] == [True, False]
    assert ms[0].exclude_reason


def test_build_dataset_uses_station_name_and_reference_window():
    ds = pairing.build_dataset(_snapshot([]))
    assert ds.site_name == "TEST RIVER NEAR NOWHERE"
    assert str(ds.reference_start) == "2012-01-01" and str(ds.reference_end) == "2024-09-25"
    assert str(pairing.reference_window("02085000")[1]) == "2025-07-06"


def test_real_snapshot_pairs_every_discharge():
    ds = pairing.load_dataset("02085000")
    assert ds.site_name.startswith("ENO RIVER")
    assert len(ds.measurements) > 700
    assert all(m.stage_ft > 0 and m.discharge_cfs > 0 for m in ds.measurements)


def test_parse_time_converts_offsets_to_utc_and_refuses_naive():
    t = pairing._parse_time("2020-05-01T10:00:00-04:00")
    assert t == datetime(2020, 5, 1, 14, tzinfo=UTC)
    assert t.utcoffset() == timedelta(0) and t.tzinfo is UTC
    assert pairing._parse_time("2020-05-01T14:00:00Z") == t
    with pytest.raises(ValueError, match="UTC offset"):
        pairing._parse_time("2020-05-01T14:00:00")


def test_offset_spelling_does_not_break_exact_pairing():
    rows = [
        _stage("v1", "2020-05-01T10:00:00-04:00", "2.0"),
        _q("v1", "2020-05-01T14:00:00+00:00", "100"),
    ]
    ms = pairing.pair_measurements(_snapshot(rows))
    assert len(ms) == 1 and ms[0].time.tzinfo is UTC
