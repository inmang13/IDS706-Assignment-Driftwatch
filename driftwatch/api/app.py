"""DriftWatch API and console. `make serve` -> http://localhost:8000/

GET  /gauges            site, name, band, score, plus the trace Replay would use
GET  /report/{site}     Report + plot payload (points, base curve, Helene date)
POST /run/{site}        run the agent team now; TraceEvents as SSE (LLM from the env / .env)
GET  /trace/{id}        a saved trace (id = file stem, or a site id for its replay trace)
GET  /replay/{id}       a saved trace re-streamed as SSE, ~0.6 s between events (?pace=0 for tests)
GET  /registry          the module specs, live first
GET  /                  console.html (Plotly served from /static, no CDN)

Every stream ends with a `finding` event: the finding card's data (cause status, Disagreement
rows, narration). CORS_ORIGINS (comma-separated) turns on CORS for those origins only.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from driftwatch.agents import trace as tr
from driftwatch.agents.fallbacks import cause_status, confidence_word
from driftwatch.modules.rating_curve import causes, pairing, rating
from driftwatch.modules.rating_curve import report as rc_report
from driftwatch.modules.rating_curve.usgs import SITES, SNAPSHOT_DIR, load_snapshot
from driftwatch.modules.registry import load_registry

load_dotenv()  # LLM / credentials from .env; never overrides the shell

HERE = Path(__file__).resolve().parent
CONSOLE = HERE / "console.html"
REPORTS = HERE.parents[1] / "reports"  # committed reports/<site>.json (make report)
STATIC = HERE / "static"  # vendored plotly.min.js: the console works with no internet
HELENE = "2024-09-27"
REPLAY_PACE_S = float(os.environ.get("REPLAY_PACE", "0.6"))
TRACE_ID = re.compile(r"^\d{8}-\d{8}T\d{6,12}Z$")  # <site>-<YYYYMMDDTHHMMSSffffffZ>
SITE_ID = re.compile(r"^\d{8}$")

app = FastAPI(title="DriftWatch", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"], allow_headers=["*"]
    )


# ---------- helpers ----------


def _check_site(site: str) -> str:
    if site not in SITES:
        raise HTTPException(404, f"unknown site {site!r}")
    return site


def _clean(x: Any) -> Any:
    """NaN/inf -> None, recursively (JSON has no NaN)."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, list | tuple):
        return [_clean(v) for v in x]
    return x


def _trace_path(trace_id: str) -> Path:
    """File stem or site id -> a trace file inside the trace dir. Rejects anything else."""
    d = tr.trace_dir()
    if SITE_ID.match(trace_id):
        p = tr.latest_trace(_check_site(trace_id), d)
        if p is None:
            raise HTTPException(404, f"no saved trace for {trace_id}")
        return p
    if not TRACE_ID.match(trace_id):
        raise HTTPException(400, "bad trace id")
    p = d / f"{trace_id}.json"
    if not p.exists():
        raise HTTPException(404, f"no trace {trace_id}")
    return p


def _post_shift_notes(doc: dict[str, Any]) -> list[str]:
    """Distinct field notes the evidence collector found since the reference window."""
    for e in doc.get("events", []):
        p = e.get("payload", {})
        if p.get("tool") == "field_notes":
            return list(p.get("result", {}).get("distinct_notes") or [])
    return []


def finding(doc: dict[str, Any]) -> dict[str, Any]:
    """The finding card's data from a saved trace.

    cause_status:
      none          Trusted: triage sent the gauge straight to the narrator, no cause named
      disagreement  the skeptic's final verdict was a Disagreement (four rows on the card)
      corroborated  a field note since the reference window maps to the final cause
      open          a cause was ranked, but no field note backs it and there is no Disagreement
    """
    fin = (doc.get("final") or {}).get("final")
    notes = _post_shift_notes(doc)
    out: dict[str, Any] = {
        "trace_id": Path(doc.get("_path", "")).stem or None,
        "site": doc.get("site"),
        "llm": doc.get("llm"),
        "started_at": doc.get("started_at"),
        "narration": (doc.get("final") or {}).get("narration"),
        "cause": None,
        "confidence": None,
        "first_cause": None,
        "objections": 0,
        "cause_status": "none",
        "supporting_notes": [],
        "disagreement": None,
    }
    if not fin:
        return out
    cause = fin.get("cause")
    support = [n for n in notes if (c := causes.cause_for_note(n)) and c.key == cause]
    out.update(
        cause=cause,
        confidence=fin.get("confidence"),
        first_cause=fin.get("first_cause"),
        objections=fin.get("objections", 0),
        supporting_notes=support,
        skeptic_argument=fin.get("skeptic_argument"),
    )
    conf = fin.get("confidence")
    out["confidence_word"] = confidence_word(conf) if conf is not None else None
    # traces from before M3 have no cause_status in final: same rule, recomputed
    out["cause_status"] = fin.get("cause_status") or cause_status(fin, notes)
    if out["cause_status"] == "disagreement":
        out["disagreement"] = fin["disagreement"]
        out["confidence_word"] = "uncertain"
    return out


def _load(path: Path) -> dict[str, Any]:
    doc = tr.load_trace(path)
    doc["_path"] = str(path)
    return doc


def _trace_info(site: str) -> dict[str, Any] | None:
    p = tr.latest_trace(site, tr.trace_dir())
    if p is None:
        return None
    doc = tr.load_trace(p)
    return {"id": p.stem, "started_at": doc.get("started_at"), "llm": doc.get("llm")}


@cache
def _report(site: str):
    return rc_report.build_report(site, "snapshot")


MISFIT_PCT = 15.0  # a reference point "misses" the curve when it sits this far off
MISFIT_SHARE = 0.20  # ... and this share of top-third reference points miss
NEWEST_N = 8  # default only; the payload passes the trust score's own recent count


def high_flow_misfit(points: list[dict[str, Any]], newest_n: int = NEWEST_N) -> dict[str, Any]:
    """C11.4: does the single-line curve miss the top third of flows in the reference window,
    while the newest readings all sit at low and middle flows? Only then is the caption true."""
    ref = [
        p
        for p in points
        if p["period"] == "reference" and p["residual_pct"] is not None and not p["excluded"]
    ]
    out: dict[str, Any] = {"show": False, "share_off": None, "cutoff_cfs": None}
    if len(ref) < 12:
        return out
    cutoff = float(np.quantile([p["discharge_cfs"] for p in ref], 2 / 3))
    top = [p for p in ref if p["discharge_cfs"] >= cutoff]
    share = sum(abs(p["residual_pct"]) > MISFIT_PCT for p in top) / len(top)
    newest = [
        p
        for p in points
        if p["period"] != "reference" and p["residual_pct"] is not None and not p["excluded"]
    ][-newest_n:]
    newest_low = bool(newest) and all(p["discharge_cfs"] < cutoff for p in newest)
    out.update(share_off=share, cutoff_cfs=cutoff, show=share >= MISFIT_SHARE and newest_low)
    return out


def stored_trend(site: str) -> dict[str, Any]:
    """trend and trend_note from the committed reports/<site>.json. Read, never recomputed:
    site_trend takes ~25 s at Mills, too slow per page load. Missing file or field -> None."""
    try:
        doc = json.loads((REPORTS / f"{site}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"trend": None, "trend_note": None}
    return {"trend": doc.get("trend"), "trend_note": doc.get("trend_note")}


@cache
def _report_payload(site: str) -> dict[str, Any]:
    """Report + everything the two plots need. Built from the snapshot, cached (it is static)."""
    rep = _report(site)
    ds = pairing.load_dataset(site, "snapshot")
    rel = rep.relationship
    top = rc_report.top_shift(rel.reference_end, rep.drift)
    split = top.time if top else None
    rows = rating.residual_table(rel, rc_report.visits_since_reference(ds))
    points = []
    for r in rows:
        t = r["time"]
        if t.date() <= rel.reference_end:
            period = "reference"
        elif split is None or t >= split:
            period = "post_shift"
        else:
            period = "between"  # after the reference window, before the detected shift
        points.append({**r, "time": t.isoformat(), "period": period})
    stages = [r["stage_ft"] for r in rows if r["stage_ft"] > rel.e]
    curve = []
    if stages:
        lo, hi = max(rel.e + 0.01, min(stages) * 0.9), max(stages) * 1.05
        n = 80
        for i in range(n + 1):
            h = lo + (hi - lo) * i / n
            curve.append({"stage_ft": h, "discharge_cfs": float(rating.predict_q(rel, h))})
    inputs = rc_report.trust_inputs(ds, rel, rep.drift, ds.fetched_at)
    recent = list(inputs.recent_residual_pct)
    channel = None
    if split is not None:
        from driftwatch.agents.tools import channel_geometry_trend  # same numbers the agents see

        geo = channel_geometry_trend(site, split)
        if geo.get("sufficient"):
            channel = {k: geo[k] for k in ("area_change_pct", "velocity_change_pct", "at_stage_ft",
                                           "n_before", "n_after")}
    return _clean(
        {
            "report": json.loads(rep.model_dump_json()),
            # "where the newest readings sit now": the same median the trust score uses
            "recent": {
                "median_pct": float(np.median(recent)) if recent else None,
                "n": len(recent),
            },
            **stored_trend(site),
            "high_flow_misfit": high_flow_misfit(points, len(recent) or NEWEST_N),
            "points": points,
            "curve": curve,
            "top_shift": json.loads(top.model_dump_json()) if top else None,
            # cross-sectional area and water speed at the same stage, before vs after the change
            "channel": channel,
            "helene": HELENE,
            "split_time": split.isoformat() if split else None,
        }
    )


def _sse(ev) -> dict[str, str]:
    return {"event": "trace", "data": ev.model_dump_json()}


# ---------- routes ----------


@app.get("/gauges")
def gauges() -> list[dict[str, Any]]:
    out = []
    for site in SITES:
        rep = _report(site)
        out.append(
            {
                "site": site,
                "name": rep.site_name,
                "band": rep.trust.band,
                "score": rep.trust.score,
                "replay": _trace_info(site),
                **_location(site),
            }
        )
    return out


@cache
def _location(site: str) -> dict[str, Any]:
    """Map position and drainage area from the snapshot's monitoring-locations record."""
    snap = load_snapshot(site)
    feats = snap.get("collections", {}).get("monitoring-locations") or [{}]
    geo = (feats[0].get("geometry") or {}).get("coordinates") or [None, None]
    area = feats[0].get("properties", {}).get("drainage_area")
    return {"lon": geo[0], "lat": geo[1], "drainage_area_mi2": area}


@app.get("/report/{site}")
def report(site: str) -> dict[str, Any]:
    return _report_payload(_check_site(site))


@cache
def _map_layers(site: str) -> dict[str, Any] | None:
    """Basin and main-stem flowlines snapshotted from USGS NLDI by scripts/fetch_nldi.py."""
    path = SNAPSHOT_DIR / "nldi" / f"{site}.json"
    if not path.exists():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {k: doc.get(k) for k in ("site", "basin", "upstream", "downstream", "upstream_km", "downstream_km")}


@app.get("/map/{site}")
def map_layers(site: str) -> dict[str, Any]:
    layers = _map_layers(_check_site(site))
    if layers is None:
        raise HTTPException(404, f"no map layers for {site}; run: python scripts/fetch_nldi.py {site}")
    return layers


@app.get("/trace/{trace_id}")
def trace(trace_id: str) -> dict[str, Any]:
    doc = _load(_trace_path(trace_id))
    doc["finding"] = finding(doc)
    doc["id"] = Path(doc.pop("_path")).stem
    return doc


@app.get("/replay/{trace_id}")
async def replay(trace_id: str, pace: float | None = Query(None, ge=0, le=5)):
    path = _trace_path(trace_id)
    doc = _load(path)
    delay = REPLAY_PACE_S if pace is None else pace

    async def gen():
        yield {
            "event": "meta",
            "data": json.dumps(
                {
                    "replay": True,
                    "id": path.stem,
                    "started_at": doc.get("started_at"),
                    "llm": doc.get("llm"),
                    "site": doc.get("site"),
                }
            ),
        }
        for i, ev in enumerate(tr.replay(path)):
            if i and delay:
                await asyncio.sleep(delay)
            yield _sse(ev)
        yield {"event": "finding", "data": json.dumps(finding(doc))}

    return EventSourceResponse(gen())


@app.post("/run/{site}")
async def run(site: str):
    _check_site(site)
    from driftwatch.agents import llm
    from driftwatch.agents.graph import run_agents

    mode = llm.mode(None)
    queue: asyncio.Queue = asyncio.Queue()

    async def gen():
        yield {"event": "meta", "data": json.dumps({"replay": False, "site": site, "llm": mode})}
        task = asyncio.create_task(run_agents(site, mode, queue))
        while True:
            get = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({get, task}, return_when=asyncio.FIRST_COMPLETED)
            if get in done:
                ev = get.result()
                yield _sse(ev)
                if ev.node == "run" and ev.status in ("completed", "error"):
                    break
                continue
            get.cancel()
            if task.exception() is not None:  # failed before it could emit "run error"
                err = f"{type(task.exception()).__name__}: {task.exception()}"[:500]
                yield {"event": "error", "data": json.dumps({"error": err})}
                return
        try:
            out = await task
        except Exception as e:  # noqa: BLE001 - the stream must report any failure
            yield {"event": "error", "data": json.dumps({"error": f"{type(e).__name__}: {e}"})}
            return
        doc = _load(Path(out["trace_path"]))
        yield {"event": "finding", "data": json.dumps(finding(doc))}

    return EventSourceResponse(gen())


@app.get("/registry")
def registry() -> list[dict[str, Any]]:
    return [s.model_dump() for s in load_registry()]


@app.get("/", include_in_schema=False)
def console():
    return FileResponse(CONSOLE, media_type="text/html")
