"""Extract, clean and merge the three USGS tables.

Three related tables per gauge, all from the USGS Water Data OGC API (cached in
data/snapshot/<site>.json):

  field-measurements    one row per reading at a field visit (stage, discharge, ...)
  channel-measurements  cross-section geometry for a discharge measurement (area, velocity, width)
  monitoring-locations  one row per gauge (name, county, drainage area, datum)

Join keys: field and channel rows share (field_visit_id, time); every row carries
monitoring_location_id ("USGS-<site>").

The field cleaning reproduces driftwatch.modules.rating_curve.pairing.pair_with_counts exactly
(tests/test_pipeline.py checks this), so the warehouse feeds the agents the same measurements the
snapshot path does.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from driftwatch.modules.rating_curve import pairing
from driftwatch.modules.rating_curve.usgs import load_snapshot

COLLECTIONS = {
    "field": "field-measurements",
    "channel": "channel-measurements",
    "sites": "monitoring-locations",
}

PAIRED_COLUMNS = [
    "site",
    "field_visit_id",
    "time",
    "stage_ft",
    "discharge_cfs",
    "rated",
    "weight",
    "control_condition",
    "approval_status",
    "excluded",
    "exclude_reason",
]
CHANNEL_COLUMNS = [
    "site",
    "field_visit_id",
    "time",
    "n_channel_rows",
    "channel_flow_cfs",
    "channel_area_ft2",
    "channel_velocity_fps",
    "channel_width_ft",
    "channel_stability",
    "channel_material",
]
SITE_COLUMNS = [
    "site",
    "site_name",
    "state_name",
    "county_name",
    "hydrologic_unit_code",
    "drainage_area_sq_mi",
    "altitude_ft",
    "vertical_datum",
    "longitude",
    "latitude",
    "fetched_at",
]
KEY = ["site", "field_visit_id", "time"]


# --------------------------------------------------------------------------- extract


def extract(site: str, table: str) -> pd.DataFrame:
    """One USGS collection for one gauge as a flat DataFrame (GeoJSON properties + lon/lat)."""
    snap = load_snapshot(site)
    feats = snap["collections"].get(COLLECTIONS[table]) or []
    rows = []
    for f in feats:
        p = dict(f.get("properties") or {})
        coords = (f.get("geometry") or {}).get("coordinates") or [None, None]
        p["longitude"], p["latitude"] = coords[0], coords[1]
        p["source_site"] = site
        p["fetched_at"] = snap.get("fetched_at")  # "as of" date for staleness scoring
        rows.append(p)
    return pd.DataFrame(rows)


def _site_code(s: pd.Series) -> pd.Series:
    return s.astype(str).str.removeprefix("USGS-")


def _positive(s: pd.Series) -> pd.Series:
    """Numeric, finite and > 0, else NaN (blank strings in the API become NaN)."""
    v = pd.to_numeric(s, errors="coerce")
    return v.where(np.isfinite(v) & (v > 0))


# --------------------------------------------------------------------------- clean


def clean_field(raw: pd.DataFrame) -> pd.DataFrame:
    """Pair each discharge with its stage reading. One row per usable discharge.

    Rules (same as pairing.pair_with_counts):
      - stage = parameter 00065 with reading_type MeanGageHeight; discharge = parameter 00060
      - pair on (field_visit_id, time) exactly; a visit can hold several discharges
      - drop discharges with no stage at that key, or with two different stages (ambiguous)
      - drop non-positive or unparsable discharge/stage values
      - rated outside Excellent/Good/Fair/Poor -> Unspecified; weight 4/3/2/1, else 1.5
      - flag (keep) Poor measurements taken 2024-09-26..28: excluded from the drift test
    """
    if raw.empty:
        return pd.DataFrame(columns=PAIRED_COLUMNS)
    df = raw[raw["time"].notna() & (raw["time"].astype(str).str.strip() != "")].copy()
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
    df["value_num"] = pd.to_numeric(df["value"], errors="coerce")
    df["site"] = _site_code(df["monitoring_location_id"])

    is_stage = (df["parameter_code"] == pairing.STAGE_CODE) & (
        df["reading_type"] == pairing.STAGE_READING
    )
    stage = df[is_stage & df["value_num"].notna()]
    stage = (
        stage.groupby(["field_visit_id", "time"])["value_num"]
        .agg(n_stage="nunique", stage_ft="first")
        .reset_index()
    )

    q = df[df["parameter_code"] == pairing.DISCHARGE_CODE].copy()
    q = q[q["value_num"].notna() & (q["value_num"] > 0)]
    q = q.merge(stage, on=["field_visit_id", "time"], how="inner")
    q = q[(q["n_stage"] == 1) & (q["stage_ft"] > 0)]

    out = pd.DataFrame(
        {
            "site": q["site"],
            "field_visit_id": q["field_visit_id"],
            "time": q["time"],
            "stage_ft": q["stage_ft"].astype(float),
            "discharge_cfs": q["value_num"].astype(float),
        }
    )
    rated = q["measurement_rated"].where(q["measurement_rated"].isin(pairing.RATED_VALUES))
    out["rated"] = rated.fillna("Unspecified")
    out["weight"] = out["rated"].map(pairing.QUALITY_WEIGHT).fillna(pairing.DEFAULT_WEIGHT)
    out["control_condition"] = q["control_condition"]
    out["approval_status"] = q["approval_status"]
    day = out["time"].dt.date
    out["excluded"] = (
        (out["rated"] == "Poor") & (day >= pairing.EXCLUDE_START) & (day <= pairing.EXCLUDE_END)
    )
    out["exclude_reason"] = np.where(out["excluded"], pairing.HELENE_REASON, None)
    return out.sort_values(["site", "time"], kind="stable").reset_index(drop=True)[PAIRED_COLUMNS]


def clean_channel(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per (site, field_visit_id, time) with the channel geometry.

    A key with several channel rows (a split channel) keeps its count but no geometry: summing
    the parts would need a convention the data doesn't document. Blank/zero/negative numbers -> NaN.
    """
    if raw.empty:
        return pd.DataFrame(columns=CHANNEL_COLUMNS)
    df = raw[raw["time"].notna() & raw["field_visit_id"].notna()].copy()
    df = df[df["time"].astype(str).str.strip() != ""]
    df["time"] = pd.to_datetime(df["time"], utc=True, format="ISO8601")
    df["site"] = _site_code(df["monitoring_location_id"])
    num = {
        "channel_flow_cfs": "channel_flow",
        "channel_area_ft2": "channel_area",
        "channel_velocity_fps": "channel_velocity",
        "channel_width_ft": "channel_width",
    }
    for new, old in num.items():
        df[new] = _positive(df[old])
    df["n_channel_rows"] = df.groupby(KEY)["field_visit_id"].transform("size")
    single = df["n_channel_rows"] == 1
    for new in num:
        df.loc[~single, new] = np.nan
    for col in ("channel_stability", "channel_material"):
        df.loc[~single, col] = None
    out = df.drop_duplicates(KEY)[CHANNEL_COLUMNS]
    return out.sort_values(KEY, kind="stable").reset_index(drop=True)


def clean_sites(raw: pd.DataFrame) -> pd.DataFrame:
    """One row per gauge with the descriptive fields the report and agents use."""
    if raw.empty:
        return pd.DataFrame(columns=SITE_COLUMNS)
    df = raw.copy()
    out = pd.DataFrame(
        {
            "site": df["monitoring_location_number"].astype(str),
            "site_name": df["monitoring_location_name"],
            "state_name": df.get("state_name"),
            "county_name": df.get("county_name"),
            "hydrologic_unit_code": df.get("hydrologic_unit_code"),
            "drainage_area_sq_mi": pd.to_numeric(df.get("drainage_area"), errors="coerce"),
            "altitude_ft": pd.to_numeric(df.get("altitude"), errors="coerce"),
            "vertical_datum": df.get("vertical_datum"),
            "longitude": pd.to_numeric(df.get("longitude"), errors="coerce"),
            "latitude": pd.to_numeric(df.get("latitude"), errors="coerce"),
            "fetched_at": pd.to_datetime(df.get("fetched_at"), utc=True, format="ISO8601"),
        }
    )
    return out.drop_duplicates("site").sort_values("site").reset_index(drop=True)


# --------------------------------------------------------------------------- merge


def merge(field: pd.DataFrame, channel: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """paired field measurements LEFT JOIN channel geometry LEFT JOIN site facts.

    One output row per paired discharge; the channel table is already one row per key, so the
    join cannot duplicate rows (checked).
    """
    m = field.merge(channel, on=KEY, how="left")
    m["n_channel_rows"] = m["n_channel_rows"].fillna(0).astype(int)
    m = m.merge(sites.drop(columns=["fetched_at"], errors="ignore"), on="site", how="left")
    if len(m) != len(field):
        raise ValueError(f"merge changed the row count: {len(field)} -> {len(m)}")
    m["year"] = m["time"].dt.year
    m["post_helene"] = m["time"] >= pd.Timestamp(pairing.EXCLUDE_START, tz="UTC")
    return m


def profile(df: pd.DataFrame) -> dict[str, Any]:
    """Small JSON-safe summary for XCom and the Airflow log."""
    return {
        "rows": len(df),
        "sites": sorted(df["site"].unique().tolist()) if "site" in df and len(df) else [],
        "null_share": {c: round(float(df[c].isna().mean()), 3) for c in df.columns},
    }
