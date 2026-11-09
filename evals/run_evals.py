"""DriftWatch evals: run evals/cases.yaml, write docs/eval_report.md.

    python evals/run_evals.py            # LLM=fallback only (offline)
    python evals/run_evals.py gemini     # also an LLM=gemini column (needs Vertex credentials)

The fallback column is always run. Cases that never touch an LLM (report, synthetic, replay)
get the same result in every column. Exit code 1 if any case fails in any column that ran.
Agent traces go to a temporary directory, never traces/ (Replay reads that).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import sys
import tempfile
import time
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # this checkout, not whatever the editable install points at

import numpy as np
import yaml

from driftwatch.agents import fallbacks, narration
from driftwatch.agents import trace as tr
from driftwatch.agents.graph import run_agents
from driftwatch.modules.rating_curve import pairing, rating, segmentation
from driftwatch.modules.rating_curve import report as rc_report

CASES = REPO / "evals" / "cases.yaml"
OUT = REPO / "docs" / "eval_report.md"
NOT_RUN = "[run on laptop]"
HOW_BUILT = """## How the synthetic cases are built

- **Steps (Eno, Swannanoa):** every gauging on or after the step date (Eno 2025-07-01,
  Swannanoa 2025-01-01) has its discharge multiplied by 1.25. The check accepts a positive
  shift dated on or after the step date and at or before the 2nd searched gauging on or after
  it. (Eno's reference window ends 2025-07-06; no searched gauging falls between the two dates,
  so none of its step is in the fit. Swannanoa's window ends 2024-09-25, before its step.)
- **Slope:** every Eno gauging from the reference start (2015-01-01) on has its discharge
  multiplied by 1 - 0.015 x years since then. It adds to Eno's own slope (-0.95 %/yr, not
  significant on the real data).
- **Flat:** every Eno gauging from the reference start on gets Q = rating(H) x a reference
  residual drawn with replacement (seed 0, fixed before running). Same dates and stages, no
  step, no slope. One seed is a smoke test; the decision log records the change-point search's
  false-alarm rate across seeds.
- **Replay:** two fallback runs on Hepco must agree on the final call, rankings, objections,
  verdict and narration; Hepco's saved Replay trace (`traces/replay_defaults.json`) must replay
  the same events twice, in seq order.
"""


class Check:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.notes: list[str] = []

    def that(self, ok: bool, what: str) -> None:
        (self.notes if ok else self.fails).append(what)


# --- shared checks -------------------------------------------------------------------------


def post_reference_shifts(rep):
    return [s for s in rep.drift.shifts if s.time.date() > rep.reference_end]


def check_report(rep, exp: dict, c: Check, ds=None) -> None:
    if "band" in exp:
        c.that(rep.trust.band == exp["band"], f"band {rep.trust.band} (want {exp['band']})")
    if "post_reference_shifts" in exp:
        n = len(post_reference_shifts(rep))
        c.that(n == exp["post_reference_shifts"], f"{n} shift(s) after the reference window")
    if "total_shifts" in exp:
        n = len(rep.drift.shifts)
        c.that(n == exp["total_shifts"], f"{n} shift(s) in the whole series")
    if "trend_significant" in exp:
        t = rep.trend
        if t is None:
            c.that(False, "no trend (window too short)")
        else:
            want_neg = exp["trend_significant"] == "lower"
            ok = t.significant and (t.slope_pct_per_year < 0) == want_neg
            c.that(
                ok,
                f"trend {t.slope_pct_per_year:+.2f} %/yr, p {t.p_value:.2g}, "
                f"CI {t.ci_low:+.2f}..{t.ci_high:+.2f}, significant={t.significant}",
            )
    if "shift_fires" in exp:
        f = exp["shift_fires"]
        at = date.fromisoformat(f["at"])
        # deadline: the Nth gauging on or after the step date, in the searched series (the one
        # shifts are dated on), so the window follows how often the gauge is visited
        k = f["by_gauging"]
        after = [
            m.time
            for m in segmentation.search_measurements(ds, rep.relationship)
            if m.time.date() >= at
        ]
        if len(after) < k:
            c.that(False, f"only {len(after)} gauging(s) on or after {at}; need {k}")
            return
        deadline = after[k - 1]
        hits = [
            s
            for s in rep.drift.shifts
            if s.direction == f["direction"] and at <= s.time.date() and s.time <= deadline
        ]
        if hits:
            s = hits[0]
            c.that(True, f"shift {s.time:%Y-%m-%d} {s.size_pct:+.1f} % ({s.size_ft:+.2f} ft)")
        else:
            got = ", ".join(f"{s.time:%Y-%m-%d} {s.size_pct:+.0f} %" for s in rep.drift.shifts)
            c.that(False, f"no {f['direction']} shift near {at}; shifts: {got or 'none'}")


def check_agents(out: dict, exp: dict, c: Check) -> None:
    fin = out.get("final")
    text = out.get("narration") or ""
    if exp.get("no_cause"):
        c.that(fin is None, "no cause named" if fin is None else f"cause {fin.get('cause')}")
        return
    if fin is None:
        c.that(False, "agents named no cause")
        return
    if "cause" in exp:
        c.that(fin["cause"] == exp["cause"], f"cause {fin['cause']} ({fin['confidence']:.2f})")
    if "cites_note" in exp:
        note = exp["cites_note"]
        hyp = next((h for h in out["ranking"]["hypotheses"] if h["cause"] == fin["cause"]), None)
        cited = bool(hyp) and any(note in e for e in hyp["evidence"])
        c.that(cited, f"'{note}' {'cited' if cited else 'NOT cited'} as {fin['cause']} evidence")
    if "disagreement" in exp:
        d = fin.get("disagreement")
        c.that(bool(d) == exp["disagreement"], f"Disagreement {'yes' if d else 'no'}")
        if d:
            n = d["field_note"]["note"]
            if "field_note_contains" in exp:
                ok = exp["field_note_contains"].lower() in n.lower()
                c.that(ok, f"field note '{n}' ({d['field_note']['date']})")
            if "best_guess_not" in exp:
                g = d["best_guess"]["cause"]
                c.that(g != exp["best_guess_not"], f"best guess {g}")
    if "cause_status" in exp:
        st = fin.get("cause_status")
        c.that(st == exp["cause_status"], f"cause_status {st}")
    if exp.get("no_mechanism_words"):
        # the field note and its fixed meaning (and a cached lead) are labelled as someone
        # else's words; DriftWatch's own sentences must carry no mechanism word
        ev = (out.get("facts") or {}).get("event_context") or {}
        nf = narration.narration_facts(out["facts"], ev.get("items")) if out.get("facts") else None
        m = fallbacks.MECHANISM_WORDS.search(narration.strip_labelled(text, nf))
        c.that(m is None, "no mechanism words" if m is None else f"names '{m.group(0)}'")


# --- synthetic datasets --------------------------------------------------------------------


def years_between(a: date, b: datetime) -> float:
    return (b.date() - a).days / 365.25


def synthetic_dataset(site: str, mod: dict):
    ds = pairing.load_dataset(site)
    ms = list(ds.measurements)
    if "step_pct" in mod:
        at = date.fromisoformat(mod["at"])
        k = 1 + mod["step_pct"] / 100
        ms = [
            (
                m.model_copy(update={"discharge_cfs": m.discharge_cfs * k})
                if m.time.date() >= at
                else m
            )
            for m in ms
        ]
    elif "slope_pct_per_year" in mod:
        s = mod["slope_pct_per_year"] / 100
        ms = [
            (
                m.model_copy(
                    update={
                        "discharge_cfs": m.discharge_cfs
                        * (1 + s * years_between(ds.reference_start, m.time))
                    }
                )
                if m.time.date() >= ds.reference_start
                else m
            )
            for m in ms
        ]
    elif "flat_seed" in mod:
        rel = rating.fit_rating(ds)
        ref = [
            m
            for m in segmentation.search_measurements(ds, rel)
            if m.time.date() <= ds.reference_end
        ]
        h_ref = np.array([m.stage_ft for m in ref])
        log_r = np.log(np.array([m.discharge_cfs for m in ref]) / rating.predict_q(rel, h_ref))
        rng = np.random.default_rng(mod["flat_seed"])
        new = []
        for m in ms:
            if m.time.date() >= ds.reference_start and m.stage_ft > rel.e:
                r = log_r[rng.integers(len(log_r))]
                q = float(rating.predict_q(rel, m.stage_ft) * np.exp(r))
                m = m.model_copy(update={"discharge_cfs": q})
            new.append(m)
        ms = new
    else:
        raise ValueError(f"unknown modify: {mod}")
    return ds.model_copy(update={"measurements": ms})


# --- replay --------------------------------------------------------------------------------

STABLE_KEYS = ("final", "narration", "ranking", "rankings", "objections", "verdict")


async def check_replay(site: str, c: Check, tmp: Path) -> None:
    a = await run_agents(site, "fallback", None, tmp)
    b = await run_agents(site, "fallback", None, tmp)
    diff = [
        k
        for k in STABLE_KEYS
        if json.dumps(a.get(k), default=str, sort_keys=True)
        != json.dumps(b.get(k), default=str, sort_keys=True)
    ]
    c.that(not diff, "two fallback runs identical" if not diff else f"runs differ in {diff}")
    path = tr.latest_trace(site, REPO / "traces")
    if path is None:
        c.that(False, "no saved trace to replay")
        return
    r1 = [e.model_dump(mode="json") for e in tr.replay(path)]
    r2 = [e.model_dump(mode="json") for e in tr.replay(path)]
    saved = sorted(tr.load_trace(path)["events"], key=lambda e: e["seq"])
    same = r1 == r2 and [e["seq"] for e in r1] == [e["seq"] for e in saved]
    same = same and [e["payload"] for e in r1] == [e["payload"] for e in saved]
    c.that(same, f"{path.name}: {len(r1)} events replay identically twice")


# --- runner --------------------------------------------------------------------------------


async def run_case(case: dict, mode: str, tmp: Path) -> tuple[Check, float]:
    c = Check()
    exp = case["expect"]
    t0 = time.perf_counter()
    try:
        kind = case["kind"]
        if kind == "agents":
            rep = rc_report.build_report(case["site"])
            check_report(rep, exp, c)
            out = await run_agents(case["site"], mode, None, tmp)
            check_agents(out, exp, c)
            fb = out["totals"]["fallbacks_used"]
            if mode != "fallback" and fb:
                c.notes.append(f"{fb} node(s) fell back to rules")
        elif kind == "report":
            check_report(rc_report.build_report(case["site"], with_trend=True), exp, c)
        elif kind == "synthetic":
            ds = synthetic_dataset(case["site"], case["modify"])
            check_report(rc_report.build_report(case["site"], ds=ds, with_trend=True), exp, c, ds)
        elif kind == "replay":
            await check_replay(case["site"], c, tmp)
        else:
            c.that(False, f"unknown kind {kind}")
    except Exception as e:  # noqa: BLE001 - a crash is a failed case, not a dead eval run
        c.that(False, f"error: {type(e).__name__}: {e}"[:300])
    return c, time.perf_counter() - t0


def cell(c: Check | None, secs: float | None) -> str:
    if c is None:
        return NOT_RUN
    head = "**FAIL**" if c.fails else "PASS"
    detail = "; ".join(c.fails + c.notes).replace("|", "/")
    return f"{head} ({secs:.1f} s) {detail}"


async def main_async(extra_modes: list[str]) -> int:
    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    modes = ["fallback"] + [m for m in extra_modes if m != "fallback"]
    results: dict[str, dict[str, tuple[Check, float]]] = {}
    with tempfile.TemporaryDirectory(prefix="dw-evals-") as d:
        tmp = Path(d)
        for case in cases:
            results[case["id"]] = {}
            for mode in modes:
                if mode != "fallback" and case["kind"] != "agents":
                    continue  # no LLM in this case: the fallback result stands for every mode
                c, secs = await run_case(case, mode, tmp)
                results[case["id"]][mode] = (c, secs)
                print(f"{case['id']:<10} {mode:<8} {cell(c, secs)}", flush=True)

    def col(case: dict, mode: str) -> str:
        if mode in results[case["id"]]:
            return cell(*results[case["id"]][mode])
        if case["kind"] != "agents" and mode in modes:
            return "same as fallback (no LLM)"
        return NOT_RUN

    n_fail = sum(1 for r in results.values() for c, _ in r.values() if c.fails)
    n_pass = sum(1 for r in results.values() if not r["fallback"][0].fails)
    total_s = sum(s for r in results.values() for _, s in r.values())
    lines = [
        "# DriftWatch eval report",
        "",
        (
            f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC by `make evals` on "
            f"{platform.node() or 'unknown'} ({platform.machine()}). Cases: `evals/cases.yaml`; "
            "runner: `evals/run_evals.py`."
        ),
        "",
        (
            f"**LLM=fallback: {n_pass}/{len(cases)} pass**, {total_s:.0f} s total. "
            "Each cell gives pass/fail, the case's wall time, and what was checked."
        ),
        "",
        (
            "Cases 4 and 9-13 never call an LLM (deterministic report, synthetic data, replay), so "
            "their result is the same in every column. The LLM=gemini column is filled by "
            "`make evals LLM=gemini` on the laptop (needs the Vertex credentials)."
        ),
        "",
        "| # | Case | LLM=fallback | LLM=gemini |",
        "|---|---|---|---|",
    ]
    for i, case in enumerate(cases, 1):
        gem = col(case, "gemini") if "gemini" in modes else NOT_RUN
        lines.append(f"| {i} | {case['name']} | {col(case, 'fallback')} | {gem} |")
    failed = [
        (i, case)
        for i, case in enumerate(cases, 1)
        if any(c.fails for c, _ in results[case["id"]].values())
    ]
    if failed:
        lines += ["", "## Why the failures fail", ""]
        for i, case in failed:
            why = case.get("note") or "not diagnosed yet."
            lines.append(f"- **{i}. {case['name']}:** {why}")
    lines += [
        "",
        HOW_BUILT,
    ]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)}")
    return 1 if n_fail else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("modes", nargs="*", help="extra LLM modes besides fallback, e.g. gemini")
    args = ap.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    import logging

    logging.basicConfig(level=logging.WARNING)
    return asyncio.run(main_async(args.modes))


if __name__ == "__main__":
    sys.exit(main())
