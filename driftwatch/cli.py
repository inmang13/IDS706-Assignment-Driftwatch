"""DriftWatch command line. `python -m driftwatch.cli report --site 03459500`.

Writes reports/<site>.json (Report schema, with the slow-drift trend) and prints one line per site.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from driftwatch.modules.rating_curve import report as rc_report
from driftwatch.modules.rating_curve.usgs import SITES

REPORTS_DIR = Path(__file__).resolve().parents[1] / "reports"


def write_report(rep, reports_dir: Path | None = None) -> Path:
    out = (reports_dir or REPORTS_DIR) / f"{rep.site}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(rep.model_dump_json(indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out


def run_cmd(args) -> int:
    from dotenv import load_dotenv

    load_dotenv()  # never override: an explicit LLM=... in the shell wins
    import asyncio

    asyncio.run(_run_sites(args.site or SITES, args.llm or None, args.trace_dir))
    return 0


async def _run_sites(sites, llm_mode, trace_dir) -> None:
    """One event loop for every site: langchain-openai caches its async HTTP client, and a
    fresh asyncio.run per site leaves it bound to a closed loop ('Event loop is closed')."""
    from driftwatch.agents.graph import run_agents

    for site in sites:
        out = await run_agents(site, llm_mode, None, trace_dir)
        fin = out.get("final")
        cause = f"{fin['cause']} ({fin['confidence']:.2f})" if fin else "no cause (Trusted)"
        t = out["totals"]
        print(
            f"== {site}: {cause} · objections {len(out.get('objections', []))} · "
            f"{t['input_tokens']}+{t['output_tokens']} tokens · {t['wall_seconds']} s"
        )
        print(out["narration"])
        print(f"trace: {out['trace_path']}")
        if t["fallbacks_used"]:
            errs = [u.get("llm_error") or u.get("rejected") for u in out.get("usage", [])]
            first = next((e for e in errs if e), "")
            print(
                f"WARNING {site}: {t['fallbacks_used']} node(s) fell back to the rules; "
                f"first reason: {first}",
                file=sys.stderr,
            )
    return 0


EVAL_DIR = Path(__file__).resolve().parents[1] / "artifacts" / "agents"
CASES = Path(__file__).resolve().parents[1] / "evals" / "cases.yaml"


def expected_bands() -> dict[str, str]:
    """Hand labels: the trust band each gauge should get, from evals/cases.yaml."""
    import yaml

    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    return {
        str(c["site"]): c["expect"]["band"]
        for c in cases
        if c.get("site")
        and "band" in (c.get("expect") or {})
        and c.get("kind") in ("agents", "report")
    }


async def _evaluate_sites(sites, llm_mode, trace_dir) -> list[dict]:
    from driftwatch.agents.graph import run_agents

    labels = expected_bands()
    rows = []
    for site in sites:
        out = await run_agents(site, llm_mode, None, trace_dir)
        f = out["facts"]
        ev, tri, fin = f.get("model_eval") or {}, f["triage"], out.get("final") or {}
        h, b, p = (
            ev.get("holdout") or {},
            ev.get("baseline_holdout") or {},
            ev.get("post_reference") or {},
        )
        want = labels.get(site)
        rows.append(
            {
                "site": site,
                "site_name": tri.get("site_name"),
                "data_source": f.get("data_source", {}).get("source"),
                "band": tri["band"],
                "expected_band": want,
                "band_correct": None if want is None else tri["band"] == want,
                "trust_score": tri["score"],
                "cause": fin.get("cause"),
                "holdout_mdape_pct": h.get("mdape_pct"),
                "holdout_within_10pct": h.get("within_10pct"),
                "baseline_mdape_pct": b.get("mdape_pct"),
                "post_mdape_pct": p.get("mdape_pct"),
                "drift_ratio": ev.get("drift_ratio"),
                "trace": out["trace_path"],
            }
        )
    return rows


def _md_table(df) -> str:
    """Plain markdown table (pandas.to_markdown needs the optional tabulate package)."""
    import pandas as pd

    def cell(v) -> str:
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    head = "| " + " | ".join(df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    body = ["| " + " | ".join(cell(v) for v in r) + " |" for r in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def evaluate_cmd(args) -> int:
    """Run the agent team on every gauge and score it: band accuracy against the hand labels,
    plus the model_evaluator's rating-model metrics. Writes artifacts/agents/evaluation.{csv,md}."""
    import asyncio

    import pandas as pd
    from dotenv import load_dotenv

    load_dotenv()
    rows = asyncio.run(_evaluate_sites(args.site or SITES, args.llm or None, args.trace_dir))
    df = pd.DataFrame(rows)
    out = args.out or EVAL_DIR
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "evaluation.csv", index=False)
    labelled = df[df["band_correct"].notna()]
    acc = float(labelled["band_correct"].mean()) if len(labelled) else float("nan")
    ok = df.dropna(subset=["holdout_mdape_pct"])
    lines = [
        "# Agent workflow evaluation",
        "",
        (
            f"- Trust-band accuracy vs hand labels: **{int(labelled['band_correct'].sum())}/"
            f"{len(labelled)} = {acc:.0%}**"
        ),
        (
            f"- Rating model, median holdout error across gauges: "
            f"**{ok['holdout_mdape_pct'].median():.1f}%** "
            f"(log-log baseline {ok['baseline_mdape_pct'].median():.1f}%)"
        ),
        f"- Share of holdout gaugings within ±10%: **{ok['holdout_within_10pct'].mean():.0%}** (mean over gauges)",
        "",
        _md_table(df.drop(columns=["trace"])),
        "",
    ]
    (out / "evaluation.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6]))
    print(df.drop(columns=["trace", "site_name"]).to_string(index=False))
    print(f"wrote {out / 'evaluation.md'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="driftwatch")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("report", help="build reports/<site>.json from the snapshot")
    rp.add_argument("--site", nargs="+", default=None, help="site id(s); default: all 8")
    rp.add_argument("--source", choices=("snapshot", "live"), default="snapshot")
    rp.add_argument("--out", type=Path, default=None)
    rn = sub.add_parser("run", help="run the agent team on a gauge; prints the narration")
    rn.add_argument("--site", nargs="+", default=None, help="site id(s); default: all 8")
    rn.add_argument("--llm", default=None, help="fallback | gemini | openrouter (default: $LLM)")
    rn.add_argument("--trace-dir", type=Path, default=None)
    ev = sub.add_parser("evaluate", help="run the agents on every gauge and score them")
    ev.add_argument("--site", nargs="+", default=None, help="site id(s); default: all 8")
    ev.add_argument("--llm", default=None, help="fallback | gemini | openrouter (default: $LLM)")
    ev.add_argument("--trace-dir", type=Path, default=None)
    ev.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the middle dot and em dash on a Windows console
    # Pairing drop counts etc. go to stderr; the summary lines stay alone on stdout.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.cmd == "run":
        return run_cmd(args)
    if args.cmd == "evaluate":
        return evaluate_cmd(args)
    if args.source != "snapshot":
        print(
            "reports read the snapshot only; run make snapshot SOURCE=live first", file=sys.stderr
        )
        return 2
    for site in args.site or SITES:
        rep = rc_report.build_report(site, args.source, with_trend=True)
        write_report(rep, args.out)
        print(rc_report.summary_line(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
