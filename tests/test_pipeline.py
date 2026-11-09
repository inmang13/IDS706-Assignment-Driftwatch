"""Part 1 pipeline: transforms, the warehouse round trip (without Postgres), and evaluation.

The key check: data that went through the pandas pipeline and the warehouse rebuild gives the
agents exactly the same measurements and channel rows as the original snapshot path.
"""

from __future__ import annotations

import pandas as pd
import pytest

from driftwatch.agents import tools
from driftwatch.modules.rating_curve import evaluate, pairing
from driftwatch.modules.rating_curve.usgs import SITES, load_snapshot
from driftwatch.pipeline import transform, warehouse

HEPCO, SWANNANOA = "03459500", "03451000"


def _tables(sites):
    raw = {t: pd.concat([transform.extract(s, t) for s in sites], ignore_index=True) for t in
           ("field", "channel", "sites")}  # fmt: skip
    field = transform.clean_field(raw["field"])
    channel = transform.clean_channel(raw["channel"])
    site_df = transform.clean_sites(raw["sites"])
    return field, channel, site_df


@pytest.fixture(scope="module")
def merged_all():
    field, channel, sites = _tables(SITES)
    m = transform.merge(field, channel, sites)
    # what read_measurements returns: merged rows + site_name + fetched_at from the sites table
    return m.merge(sites[["site", "fetched_at"]], on="site", how="left"), field, sites


@pytest.mark.parametrize("site", SITES)
def test_clean_field_matches_pairing(site, merged_all):
    _, field, _ = merged_all
    expected, _ = pairing.pair_with_counts(load_snapshot(site))
    got = field[field["site"] == site]
    assert len(got) == len(expected)
    for m, r in zip(expected, got.itertuples(index=False), strict=True):
        assert (m.field_visit_id, m.time, m.stage_ft, m.discharge_cfs) == (
            r.field_visit_id,
            r.time.to_pydatetime(),
            r.stage_ft,
            r.discharge_cfs,
        )
        assert (m.rated, m.weight, m.excluded) == (r.rated, r.weight, bool(r.excluded))


def test_merge_keeps_one_row_per_discharge(merged_all):
    m, field, sites = merged_all
    assert len(m) == len(field)
    assert m["site_name"].notna().all()
    assert set(m["site"]) == set(sites["site"]) == set(SITES)


def test_channel_split_keys_have_no_geometry():
    raw = pd.DataFrame(
        {
            "monitoring_location_id": ["USGS-1"] * 3,
            "field_visit_id": ["v1", "v1", "v2"],
            "time": ["2020-01-01T00:00:00+00:00"] * 3,
            "channel_flow": ["10", "20", "30"],
            "channel_area": ["5", "6", ""],
            "channel_velocity": ["2", "3", "-1"],
            "channel_width": ["1", "1", "1"],
            "channel_stability": ["Stable"] * 3,
            "channel_material": ["Sand"] * 3,
        }
    )
    c = transform.clean_channel(raw).set_index("field_visit_id")
    assert c.loc["v1", "n_channel_rows"] == 2 and pd.isna(c.loc["v1", "channel_area_ft2"])
    assert c.loc["v2", "n_channel_rows"] == 1
    assert pd.isna(c.loc["v2", "channel_area_ft2"]) and pd.isna(c.loc["v2", "channel_velocity_fps"])


@pytest.mark.parametrize("site", [HEPCO, SWANNANOA, "03455000"])
def test_warehouse_rebuild_matches_snapshot(site, merged_all, monkeypatch):
    """Agents in warehouse mode see the same dataset, channel rows and trust band."""
    frame = merged_all[0]
    tools.clear_caches()
    snap_ds = tools.dataset(site)
    snap_rows = tools.channel_rows(site)
    snap_band = tools.report(site).trust.band

    monkeypatch.setenv(tools.SOURCE_ENV, "warehouse")
    monkeypatch.setattr(warehouse, "read_measurements", lambda s=None, conn=None: frame)
    tools.clear_caches()
    try:
        wh = tools.dataset(site)
        assert wh.source == "warehouse" and tools.load_info(site)["source"] == "warehouse"
        assert wh.fetched_at == snap_ds.fetched_at
        assert [m.model_dump(exclude={"pairing"}) for m in wh.measurements] == [
            m.model_dump(exclude={"pairing"}) for m in snap_ds.measurements
        ]
        assert tools.channel_rows(site) == snap_rows
        assert tools.report(site).trust.band == snap_band
    finally:
        tools.clear_caches()


def test_warehouse_down_falls_back_to_snapshot(monkeypatch):
    monkeypatch.setenv(tools.SOURCE_ENV, "warehouse")

    def boom(*a, **k):
        raise ConnectionError("no db")

    monkeypatch.setattr(warehouse, "read_measurements", boom)
    tools.clear_caches()
    try:
        info = tools.load_info(HEPCO)
        assert info["source"] == "snapshot" and "no db" in info["warehouse_error"]
        assert info["n_measurements"] > 0
    finally:
        tools.clear_caches()


def test_evaluate_rating_scores():
    tools.clear_caches()
    out = evaluate.evaluate_rating(tools.dataset(SWANNANOA))
    assert out["n_train"] + out["n_test"] == out["n_reference"]
    assert 0 <= out["holdout"]["within_10pct"] <= 1
    assert out["holdout"]["mdape_pct"] < 15  # a healthy rating fits its own future gaugings
    # Hepco drifted: much worse after the reference window than on its holdout
    hep = evaluate.evaluate_rating(tools.dataset(HEPCO))
    assert hep["drift_ratio"] > 2


def test_scores_ignores_out_of_domain():
    s = evaluate.scores([5.0, -15.0, float("nan")])
    assert s == {"n": 2, "mdape_pct": 10.0, "within_10pct": 0.5, "bias_pct": -5.0}
