"""USGS rating-curve pipeline: ingest -> clean (3 tables in parallel) -> merge -> Postgres -> analysis.

Graph (what the Airflow Graph tab shows):

    list_sites
      ├─▶ [field_measurements]    extract ×8 sites (mapped, parallel) ─▶ clean ─▶ check
      ├─▶ [channel_measurements]  extract ×8 sites (mapped, parallel) ─▶ clean ─▶ check
      └─▶ [monitoring_locations]  extract ×8 sites (mapped, parallel) ─▶ clean ─▶ check
                       │ (all three groups run side by side)
                       ▼
                merge_tables ─▶ load_warehouse ─┬─▶ export_clean_csv
                                                └─▶ [analysis] evaluate_site ×8 (mapped) ─▶ summarize_and_plot

Scheduling: daily at 06:00 UTC, no catchup, one run at a time. Each run writes to its own
folder (artifacts/pipeline/runs/<run_id>/) and replaces the warehouse tables in one transaction,
so re-running a day is safe.

Parallelism: the LocalExecutor runs independent tasks at the same time: the three table groups
run side by side, and inside each group the 8 per-site extracts are dynamically mapped tasks.
The analysis fans out one evaluate task per site the same way.

All the real logic lives in driftwatch/pipeline/ and driftwatch/modules/rating_curve/evaluate.py;
this file only wires tasks together.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow.decorators import dag, task, task_group
from airflow.operators.python import get_current_context

REPO = Path(os.environ.get("DRIFTWATCH_REPO", "/repo"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ARTIFACTS = REPO / "artifacts" / "pipeline"
CLEAN_CSV = REPO / "data" / "cleaned" / "measurements.csv"


def _run_dir(context) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", context["run_id"])
    d = ARTIFACTS / "runs" / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


@dag(
    dag_id="usgs_rating_pipeline",
    description="USGS field + channel + site tables -> Postgres -> rating-curve model evaluation",
    schedule="0 6 * * *",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(seconds=30)},
    tags=["hw", "usgs", "rating-curve"],
)
def usgs_rating_pipeline():
    @task
    def list_sites() -> list[str]:
        from driftwatch.modules.rating_curve.usgs import SITES

        return list(SITES)

    # ------------------------------------------------------------------ ingest + clean

    @task(map_index_template="{{ site_label }}")
    def extract(site: str, table: str, **context) -> str:
        """One gauge, one table -> raw pickle in this run's folder."""
        from driftwatch.pipeline import transform

        get_current_context()["site_label"] = site  # names the mapped task by gauge in the UI

        df = transform.extract(site, table)
        path = _run_dir(context) / "raw" / f"{table}_{site}.pkl"
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(path)
        print(f"{table} {site}: {len(df)} raw rows")
        return str(path)

    @task
    def clean(raw_paths: list[str], table: str, **context) -> str:
        import pandas as pd

        from driftwatch.pipeline import transform

        raw = pd.concat([pd.read_pickle(p) for p in raw_paths], ignore_index=True)
        fn = {
            "field": transform.clean_field,
            "channel": transform.clean_channel,
            "sites": transform.clean_sites,
        }[table]
        out = fn(raw)
        path = _run_dir(context) / "clean" / f"{table}.pkl"
        path.parent.mkdir(parents=True, exist_ok=True)
        out.to_pickle(path)
        print(f"{table}: {len(raw)} raw rows -> {len(out)} clean rows")
        return str(path)

    @task
    def check(path: str, table: str) -> str:
        """Data-quality gate: fail the run (red task) instead of loading bad data."""
        import pandas as pd

        from driftwatch.pipeline import transform

        df = pd.read_pickle(path)
        if df.empty:
            raise ValueError(f"{table}: no rows after cleaning")
        if table == "field":
            bad = df[(df["stage_ft"] <= 0) | (df["discharge_cfs"] <= 0)]
            if len(bad):
                raise ValueError(f"field: {len(bad)} non-positive stage/discharge rows")
            if df.duplicated(["field_visit_id", "time", "discharge_cfs"]).any():
                raise ValueError("field: duplicate discharge rows")
        if table == "channel" and df.duplicated(transform.KEY).any():
            raise ValueError("channel: more than one row per (site, visit, time)")
        if table == "sites" and df["site"].duplicated().any():
            raise ValueError("sites: duplicate site rows")
        print(json.dumps(transform.profile(df), indent=1)[:2000])
        return path

    def table_group(group_id: str, table: str):
        @task_group(group_id=group_id)
        def _group(sites: list[str]) -> str:
            raw = extract.partial(table=table).expand(site=sites)
            return check(clean(raw, table), table)

        return _group

    # ------------------------------------------------------------------ merge + load

    @task
    def merge_tables(field_path: str, channel_path: str, sites_path: str, **context) -> str:
        import pandas as pd

        from driftwatch.pipeline import transform

        merged = transform.merge(
            pd.read_pickle(field_path), pd.read_pickle(channel_path), pd.read_pickle(sites_path)
        )
        path = _run_dir(context) / "clean" / "merged.pkl"
        merged.to_pickle(path)
        with_channel = int((merged["n_channel_rows"] == 1).sum())
        print(f"merged: {len(merged)} rows, {with_channel} with single-channel geometry")
        return path.as_posix()

    @task
    def load_warehouse(merged_path: str, sites_path: str, **context) -> dict:
        import pandas as pd

        from driftwatch.pipeline import warehouse

        counts = warehouse.load(
            pd.read_pickle(merged_path),
            pd.read_pickle(sites_path),
            run_id=context["run_id"],
            logical_date=str(context["logical_date"]),
        )
        print(f"loaded {counts} into {warehouse.url().split('@')[-1]}")
        return counts

    @task
    def export_clean_csv(_counts: dict) -> str:
        """Readable copy of the warehouse table for the README / graders (read back from the DB)."""
        from driftwatch.pipeline import warehouse

        df = warehouse.read_measurements()
        CLEAN_CSV.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(CLEAN_CSV, index=False)
        return str(CLEAN_CSV)

    # ------------------------------------------------------------------ analysis

    @task(map_index_template="{{ site_label }}")
    def evaluate_site(site: str, _counts: dict) -> dict:
        """Read one gauge back from Postgres, train/test the rating model, score drift."""
        from driftwatch.modules.rating_curve import evaluate
        from driftwatch.pipeline import warehouse

        get_current_context()["site_label"] = site

        ds = warehouse.dataset_from_frame(warehouse.read_measurements(site), site)
        out = evaluate.evaluate_rating(ds)
        print(json.dumps(out, indent=1))
        return out

    @task
    def summarize_and_plot(results: list[dict], **context) -> str:
        import pandas as pd

        from driftwatch.pipeline import analysis, warehouse

        run = _run_dir(context)
        table = analysis.metrics_table(list(results))
        table.to_csv(run / "model_metrics.csv", index=False)
        analysis.plot_metrics(table, run / "model_metrics.png")
        analysis.plot_residuals(warehouse.read_measurements(), run / "residuals_over_time.png")
        (run / "model_metrics.json").write_text(json.dumps(list(results), indent=1, default=str))
        latest = ARTIFACTS / "latest"
        shutil.rmtree(latest, ignore_errors=True)
        shutil.copytree(run, latest, ignore=shutil.ignore_patterns("raw", "clean"))
        with pd.option_context("display.width", 200, "display.max_columns", 20):
            print(table.to_string(index=False))
        return str(latest)

    # ------------------------------------------------------------------ wiring

    sites = list_sites()
    field = table_group("field_measurements", "field")(sites)
    channel = table_group("channel_measurements", "channel")(sites)
    site_meta = table_group("monitoring_locations", "sites")(sites)

    merged = merge_tables(field, channel, site_meta)
    counts = load_warehouse(merged, site_meta)
    export_clean_csv(counts)

    @task_group(group_id="analysis")
    def analysis_group(sites: list[str], counts: dict):
        results = evaluate_site.partial(_counts=counts).expand(site=sites)
        return summarize_and_plot(results)

    analysis_group(sites, counts)


usgs_rating_pipeline()
