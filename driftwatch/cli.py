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
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the middle dot and em dash on a Windows console
    # Pairing drop counts etc. go to stderr; the summary lines stay alone on stdout.
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if args.cmd == "run":
        return run_cmd(args)
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
