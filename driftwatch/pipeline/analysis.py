"""Analysis step of the DAG: one metrics table + two PNGs, from data read back out of Postgres."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from driftwatch.modules.rating_curve import pairing, rating

HELENE = pd.Timestamp(pairing.EXCLUDE_START, tz="UTC")  # start of the Helene flood window


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def _short(name: str | None) -> str:
    """'PIGEON RIVER NEAR HEPCO, NC' -> 'Pigeon R.\\nnr Hepco' (fits under one bar group)."""
    if not name:
        return ""
    n = name.split(",")[0].title().replace(" River", " R.")
    for sep in (" Near ", " At "):
        if sep in n:
            river, place = n.split(sep, 1)
            return f"{river}\n{'nr' if sep == ' Near ' else 'at'} {place}"
    return n


def metrics_table(results: list[dict]) -> pd.DataFrame:
    """One row per gauge from evaluate.evaluate_rating outputs."""
    rows = []
    for r in results:
        h, b, p = (
            r.get("holdout") or {},
            r.get("baseline_holdout") or {},
            r.get("post_reference") or {},
        )
        rows.append(
            {
                "site": r["site"],
                "site_name": r.get("site_name"),
                "n_train": r.get("n_train"),
                "n_test": r.get("n_test"),
                "holdout_mdape_pct": h.get("mdape_pct"),
                "holdout_within_10pct": h.get("within_10pct"),
                "baseline_mdape_pct": b.get("mdape_pct"),
                "beats_baseline": r.get("beats_baseline"),
                "n_post": p.get("n"),
                "post_mdape_pct": p.get("mdape_pct"),
                "post_bias_pct": p.get("bias_pct"),
                "drift_ratio": r.get("drift_ratio"),
                "error": r.get("error"),
            }
        )
    return pd.DataFrame(rows).sort_values("site").reset_index(drop=True)


def plot_metrics(table: pd.DataFrame, path: Path) -> Path:
    """Grouped bars per gauge: model holdout error, baseline holdout error, post-reference error."""
    plt = _plt()
    t = table.dropna(subset=["holdout_mdape_pct"])
    x = np.arange(len(t))
    w = 0.27
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.bar(x - w, t["holdout_mdape_pct"], w, label="Rating model, holdout", color="#2a6f97")
    ax.bar(x, t["baseline_mdape_pct"], w, label="Log-log baseline, holdout", color="#9fb4c7")
    ax.bar(
        x + w, t["post_mdape_pct"], w, label="Rating model, after reference window", color="#d1495b"
    )
    ax.set_xticks(x, [f"{s}\n{_short(n)}" for s, n in zip(t["site"], t["site_name"])], fontsize=7)
    ax.set_ylabel("Median absolute % error in discharge")
    ax.set_title("Rating-curve model: holdout accuracy vs. error after Hurricane Helene")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def residuals(df: pd.DataFrame) -> pd.DataFrame:
    """% residual of every gauging against its site's base rating (fit on the reference window)."""
    from driftwatch.pipeline import warehouse

    parts = []
    for site in sorted(df["site"].unique()):
        ds = warehouse.dataset_from_frame(df, site)
        rel = rating.fit_rating(ds)
        rt = pd.DataFrame(rating.residual_table(rel, ds.measurements))
        rt["site"], rt["site_name"] = site, ds.site_name
        parts.append(rt)
    out = pd.concat(parts, ignore_index=True)
    out["time"] = pd.to_datetime(out["time"], utc=True)
    return out


def plot_residuals(df: pd.DataFrame, path: Path, since: str = "2018-01-01") -> Path:
    """Small multiples: residual % over time per gauge, Helene marked."""
    plt = _plt()
    r = residuals(df)
    r = r[(r["time"] >= pd.Timestamp(since, tz="UTC")) & ~r["excluded"]]
    sites = sorted(r["site"].unique())
    ncol = 4
    nrow = int(np.ceil(len(sites) / ncol))
    fig, axes = plt.subplots(nrow, ncol, figsize=(13, 3.0 * nrow), sharex=True, squeeze=False)
    for ax, site in zip(axes.flat, sites):
        s = r[r["site"] == site]
        pre, post = s[s["time"] < HELENE], s[s["time"] >= HELENE]
        ax.axhline(0, color="#888", lw=0.8)
        ax.axvline(HELENE, color="#d1495b", lw=0.8, ls="--")
        ax.scatter(pre["time"], pre["residual_pct"], s=9, color="#2a6f97", label="before Helene")
        ax.scatter(post["time"], post["residual_pct"], s=12, color="#e07a1f", label="after Helene")
        ax.set_title(f"{site} {(s['site_name'].iloc[0] or '')[:28]}", fontsize=8)
        ax.set_ylim(-60, 60)
        ax.tick_params(labelsize=7)
        ax.spines[["top", "right"]].set_visible(False)
    for ax in list(axes.flat)[len(sites) :]:
        ax.set_visible(False)
    axes.flat[0].legend(frameon=False, fontsize=7)
    fig.supylabel("Measured vs. rated discharge (%)", fontsize=9)
    fig.suptitle("Field measurements against each gauge's pre-storm rating curve", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path
