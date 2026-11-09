"""Postgres warehouse: the DAG loads the merged table here; the analysis task and the agents read
it back.

Tables
  sites          one row per gauge (clean_sites)
  measurements   one row per paired discharge, with channel geometry and site facts (merge)
  pipeline_runs  one row per DAG run: when it ran and how many rows each table got

Connection: WAREHOUSE_URL, default postgresql://driftwatch:driftwatch@localhost:5433/driftwatch
(the `warehouse` service in docker-compose.yml, published on host port 5433). Inside the compose
network the DAG and the app use host `warehouse`, port 5432.
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pandas as pd

from driftwatch.core.schemas import Dataset, Measurement
from driftwatch.modules.rating_curve import pairing

DEFAULT_URL = "postgresql://driftwatch:driftwatch@localhost:5433/driftwatch"

DDL = """
CREATE TABLE IF NOT EXISTS sites (
    site                 TEXT PRIMARY KEY,
    site_name            TEXT,
    state_name           TEXT,
    county_name          TEXT,
    hydrologic_unit_code TEXT,
    drainage_area_sq_mi  DOUBLE PRECISION,
    altitude_ft          DOUBLE PRECISION,
    vertical_datum       TEXT,
    longitude            DOUBLE PRECISION,
    latitude             DOUBLE PRECISION,
    fetched_at           TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS measurements (
    site                 TEXT NOT NULL REFERENCES sites(site),
    field_visit_id       TEXT NOT NULL,
    time                 TIMESTAMPTZ NOT NULL,
    stage_ft             DOUBLE PRECISION NOT NULL,
    discharge_cfs        DOUBLE PRECISION NOT NULL,
    rated                TEXT NOT NULL,
    weight               DOUBLE PRECISION NOT NULL,
    control_condition    TEXT,
    approval_status      TEXT,
    excluded             BOOLEAN NOT NULL,
    exclude_reason       TEXT,
    n_channel_rows       INTEGER NOT NULL,
    channel_flow_cfs     DOUBLE PRECISION,
    channel_area_ft2     DOUBLE PRECISION,
    channel_velocity_fps DOUBLE PRECISION,
    channel_width_ft     DOUBLE PRECISION,
    channel_stability    TEXT,
    channel_material     TEXT,
    year                 INTEGER NOT NULL,
    post_helene          BOOLEAN NOT NULL
);
CREATE INDEX IF NOT EXISTS measurements_site_time ON measurements (site, time);
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id        TEXT PRIMARY KEY,
    logical_date  TEXT,
    loaded_at     TIMESTAMPTZ DEFAULT now(),
    n_sites       INTEGER,
    n_measurements INTEGER
);
"""

SITE_COLS = [
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
MEAS_COLS = [
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
    "n_channel_rows",
    "channel_flow_cfs",
    "channel_area_ft2",
    "channel_velocity_fps",
    "channel_width_ft",
    "channel_stability",
    "channel_material",
    "year",
    "post_helene",
]


def url() -> str:
    return os.environ.get("WAREHOUSE_URL", DEFAULT_URL)


def connect(dsn: str | None = None, timeout: int = 5):
    import psycopg2  # imported here so the snapshot path never needs the driver

    return psycopg2.connect(dsn or url(), connect_timeout=timeout)


def _py(v: Any) -> Any:
    """numpy/pandas scalars -> plain Python for psycopg2; NaN/NaT -> NULL."""
    if v is None or (isinstance(v, float) and np.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.generic):
        return v.item()
    return v


def _rows(df: pd.DataFrame, cols: list[str]) -> list[tuple]:
    return [tuple(_py(v) for v in r) for r in df[cols].itertuples(index=False, name=None)]


def load(
    merged: pd.DataFrame, sites: pd.DataFrame, run_id: str, logical_date: str, conn=None
) -> dict[str, int]:
    """Replace the warehouse contents with this run's tables in one transaction (idempotent:
    re-running a DAG run leaves the same rows)."""
    from psycopg2.extras import execute_values

    own = conn is None
    conn = conn or connect()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(DDL)
            cur.execute("TRUNCATE measurements, sites")
            execute_values(
                cur,
                f"INSERT INTO sites ({', '.join(SITE_COLS)}) VALUES %s",
                _rows(sites, SITE_COLS),
            )
            execute_values(
                cur,
                f"INSERT INTO measurements ({', '.join(MEAS_COLS)}) VALUES %s",
                _rows(merged, MEAS_COLS),
                page_size=2000,
            )
            cur.execute(
                "INSERT INTO pipeline_runs (run_id, logical_date, n_sites, n_measurements) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (run_id) DO UPDATE SET "
                "loaded_at = now(), n_sites = EXCLUDED.n_sites, "
                "n_measurements = EXCLUDED.n_measurements",
                (run_id, logical_date, len(sites), len(merged)),
            )
    finally:
        if own:
            conn.close()
    return {"sites": len(sites), "measurements": len(merged)}


def read_measurements(site: str | None = None, conn=None) -> pd.DataFrame:
    """The merged table (optionally one gauge), time-ordered, joined to the site name."""
    own = conn is None
    conn = conn or connect()
    try:
        sql = (
            "SELECT m.*, s.site_name, s.fetched_at FROM measurements m JOIN sites s USING (site) "
            + ("WHERE m.site = %s " if site else "")
            + "ORDER BY m.site, m.time"
        )
        with conn.cursor() as cur:
            cur.execute(sql, (site,) if site else None)
            cols = [d[0] for d in cur.description]
            df = pd.DataFrame(cur.fetchall(), columns=cols)
    finally:
        if own:
            conn.close()
    if not df.empty:
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df["fetched_at"] = pd.to_datetime(df["fetched_at"], utc=True)
    return df


def dataset_from_frame(df: pd.DataFrame, site: str) -> Dataset:
    """Rebuild the Dataset the rating code expects from warehouse rows for one gauge."""
    rows = df[df["site"] == site].sort_values("time", kind="stable")
    if rows.empty:
        raise LookupError(f"no warehouse measurements for site {site}")
    start, end = pairing.reference_window(site)
    ms = [
        Measurement(
            site=site,
            field_visit_id=r.field_visit_id,
            time=r.time.to_pydatetime(),
            stage_ft=float(r.stage_ft),
            discharge_cfs=float(r.discharge_cfs),
            rated=r.rated,
            weight=float(r.weight),
            control_condition=_py(r.control_condition),
            approval_status=_py(r.approval_status),
            excluded=bool(r.excluded),
            exclude_reason=_py(r.exclude_reason),
        )
        for r in rows.itertuples(index=False)
    ]
    name = rows["site_name"].iloc[0] if "site_name" in rows else None
    fetched = rows["fetched_at"].iloc[0] if "fetched_at" in rows else None
    return Dataset(
        site=site,
        site_name=_py(name),
        source="warehouse",
        fetched_at=_py(fetched),
        reference_start=start,
        reference_end=end,
        measurements=ms,
        metadata={"warehouse_rows": len(ms)},
    )


def channel_props_from_frame(df: pd.DataFrame, site: str) -> dict[tuple, list[dict]]:
    """(field_visit_id, time) -> channel rows, shaped like the snapshot's channel properties so
    tools.channel_rows applies the same filters. A split-channel key gets n copies, which that
    function skips just as it skips several raw rows on one key."""
    rows = df[(df["site"] == site) & (df["n_channel_rows"] > 0)]
    out: dict[tuple, list[dict]] = {}
    for r in rows.drop_duplicates(["field_visit_id", "time"]).itertuples(index=False):
        p = {
            "channel_area": _py(r.channel_area_ft2),
            "channel_velocity": _py(r.channel_velocity_fps),
            "channel_width": _py(r.channel_width_ft),
        }
        out[(r.field_visit_id, r.time.to_pydatetime())] = [p] * int(r.n_channel_rows)
    return out
