"""The investigator team: a LangGraph StateGraph over one gauge.

    triage ──Trusted──────────────────────────────────────────▶ narrator
       └─Watch/Stale─▶ evidence_collector ─▶ hypothesis_ranker ─▶ skeptic ─accept─▶ narrator
                                                   ▲               │
                                                   └──object (≤2)──┘

triage            no LLM: reads the M1 Report (band, score, residual, top shift, M1 cause).
evidence_collector no LLM: runs the four tools in tools.py.
hypothesis_ranker LLM (or fallback): ranked causes, always incl. datum_change and inconclusive.
skeptic           LLM on a different family (or fallback): accept, or a typed objection.
                  A third objection does not loop again; it goes to the narrator as unresolved.
narrator          LLM (or fallback): <= 200 words, report voice; facts and fixed sentences
                  come from narration.py, and the guard there checks the text.

Any LLM failure (exception, unparsable output, a guard below) falls back to the deterministic
node for that step; the trace payload records it. The loop count lives in the state, so no
model output can make the graph loop forever.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any, TypedDict

import numpy as np
from langgraph.graph import END, START, StateGraph

from driftwatch.agents import context, fallbacks, llm, narration, tools
from driftwatch.agents.models import (
    CAUSE_KEYS,
    REQUIRED_CAUSES,
    Hypothesis,
    Narration,
    Ranking,
    SkepticVerdict,
)
from driftwatch.agents.trace import TraceRecorder
from driftwatch.modules.rating_curve import report as rc_report

MAX_LOOPS = 2  # skeptic objections that send the ranker round again
MAX_WORDS = narration.MAX_WORDS


class AgentState(TypedDict, total=False):
    site: str
    llm: str
    facts: dict[str, Any]  # triage + evidence, what the LLM nodes see
    ranking: dict[str, Any]
    rankings: list[dict[str, Any]]
    objections: list[dict[str, Any]]
    verdict: dict[str, Any]
    final: dict[str, Any] | None
    narration: str
    usage: list[dict[str, Any]]


def _llm_failed(e: Exception) -> dict[str, Any]:
    """Trace meta for a node whose model call (or model construction) failed: rules used."""
    msg = f"{type(e).__name__}: {e}"[:300]
    return {"model": "fallback", "llm_error": msg, "warning": f"LLM unavailable, used rules: {msg}"}


def _dump(x: Any) -> str:
    return json.dumps(x, indent=1, default=str)


# --------------------------------------------------------------------------- deterministic nodes


def triage_facts(site: str) -> dict[str, Any]:
    rep = tools.report(site)
    ds = tools.dataset(site)
    as_of = ds.fetched_at
    inputs = rc_report.trust_inputs(ds, rep.relationship, rep.drift, as_of)
    med = float(np.median(inputs.recent_residual_pct)) if inputs.recent_residual_pct else 0.0
    top = rc_report.top_shift(rep.relationship.reference_end, rep.drift)
    return {
        "site": site,
        "site_name": rep.site_name,
        "band": rep.trust.band,
        "score": round(rep.trust.score, 1),
        "score_display": f"Trust score {rep.trust.score:.0f}/100 ({rep.trust.band}).",
        "deductions": [d.model_dump() for d in rep.trust.deductions],
        "recent_median_residual_pct": round(med, 1),
        "normal_scatter_pct": round(inputs.normal_scatter_pct, 1),
        "direction": "positive" if med > 0 else "negative",
        # direction words are computed here, never inferred by the narrator from a signed number
        "direction_phrase": "above the rating" if med > 0 else "below the rating",
        "published_flows": "too low" if med > 0 else "too high",
        "off_by_pct": round(abs(med), 1),
        "days_since_last_visit": (
            round(inputs.days_since_last) if inputs.days_since_last is not None else None
        ),
        "n_visits_last_12_months": inputs.n_last_year,
        "latest_control_note": _latest_note(ds),
        "recent_rated": list(inputs.recent_rated),
        "top_shift": top.model_dump(mode="json") if top else None,
        "reference_window": [
            str(rep.relationship.reference_start),
            str(rep.relationship.reference_end),
        ],
        "m1_cause": rep.likely_cause,
        "m1_why": rep.narrative,
    }


def _latest_note(ds) -> str | None:
    visits = rc_report.visits_since_reference(ds)
    return (visits[-1].control_condition or None) if visits else None


def collect_evidence(site: str, triage: dict[str, Any]) -> dict[str, Any]:
    split = triage["top_shift"]["time"] if triage["top_shift"] else None
    return {
        "channel_geometry": tools.channel_geometry_trend(site, split),
        "field_notes": tools.field_notes(site),
        "flood_context": tools.flood_context(site, split),
        "site_metadata": tools.site_metadata(site),
        # cached web leads (make context); never searched at run time
        "event_context": context.load(site),
    }


# --------------------------------------------------------------------------- guards on LLM output


def clean_ranking(r: Ranking, facts: dict[str, Any], objections: list[dict]) -> Ranking:
    """Catalog keys only, no duplicates, sign_matches recomputed from the catalog,
    datum_change + inconclusive always present, sorted by confidence."""
    direction = facts["triage"]["direction"]
    seen: dict[str, Hypothesis] = {}
    for h in r.hypotheses:
        if h.cause in CAUSE_KEYS and h.cause not in seen:
            seen[h.cause] = h.model_copy(
                update={"sign_matches": fallbacks._sign_ok(h.cause, direction)}
            )
    if REQUIRED_CAUSES[0] not in seen or REQUIRED_CAUSES[1] not in seen:
        fb = {h.cause: h for h in fallbacks.rank(facts, objections).hypotheses}
        for k in REQUIRED_CAUSES:
            seen.setdefault(k, fb[k])
    total = sum(h.confidence for h in seen.values()) or 1.0  # padding can break the sum-to-1
    hyps = sorted(
        (
            h.model_copy(update={"confidence": round(h.confidence / total, 3)})
            for h in seen.values()
        ),
        key=lambda h: -h.confidence,
    )
    return Ranking(hypotheses=hyps, reasoning=r.reasoning)


NARRATOR_FIELDS = (
    "site_name",
    "band",
    "score",
    "score_display",
    "direction_phrase",
    "published_flows",
    "off_by_pct",
    "normal_scatter_pct",
    "days_since_last_visit",
    "n_visits_last_12_months",
    "latest_control_note",
    "recent_rated",
)


def narrator_final(final: dict | None) -> dict | None:
    """The team's call as the narrator sees it. An open cause is passed without the cause, its
    confidence or the skeptic's argument, so the model has no mechanism to name."""
    if final and final.get("cause_status") == "open":
        return {"cause_status": "open", "recommended_check": fallbacks.OPEN_CHECK}
    return final


def _cause_label(final: dict | None) -> str | None:
    if not final:
        return None
    if final.get("disagreement"):
        return fallbacks.LABEL[final["disagreement"]["best_guess"]["cause"]].lower()
    if final.get("cause_status") == "open":
        return None
    return fallbacks.LABEL[final["cause"]].lower()


def _cause_conf(final: dict | None) -> float | None:
    if not final or final.get("cause_status") == "open":
        return None
    if final.get("disagreement"):
        return final["disagreement"]["best_guess"]["confidence"]
    return final.get("confidence")


def narrator_view(
    facts: dict[str, Any], final: dict | None = None, nf: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Everything the narrator may say, and nothing else. Direction is words, size is unsigned:
    signed residuals, signed shift sizes and the score-deduction prose are left out so the model
    can neither infer (and flip) the direction nor pick up claims that aren't facts."""
    t = facts["triage"]
    v = {k: t[k] for k in NARRATOR_FIELDS if k in t}
    v["recent_median_residual"] = f"{t['off_by_pct']} % {t['direction_phrase']}"
    if t.get("top_shift"):
        v["shift_began"] = t["top_shift"]["time"][:10]
        v["measurements_since_shift"] = t["top_shift"]["n_after"]
    if final:
        v["cause_status"] = final.get("cause_status")
    if nf is not None:
        # computed facts for the narration; the signed shift is given as words + unsigned size
        keep = (
            "river_name",
            "county",
            "rating_sentence",
            "change_date",
            "level_change_ft",
            "level_word",
            "at_stage_ft",
            "flow_change_pct",
            "area_change_pct",
            "velocity_change_pct",
            "check_pct",
            "check_agrees",
            "flood",
            "window",
            "helene",
            "note",
            "lead",
        )
        v["narration_facts"] = {k: nf[k] for k in keep if nf.get(k) is not None}
        if nf.get("curve_cfs") is not None:
            v["narration_facts"]["curve_cfs"] = round(nf["curve_cfs"])
            v["narration_facts"]["flow_change_cfs_unsigned"] = round(abs(nf["flow_change_cfs"]))
    return v


def expected_confidence_word(final: dict | None) -> str:
    if final is None:
        return "n/a"
    if final.get("disagreement") or final.get("cause_status") == "open":
        return "uncertain"
    return fallbacks.confidence_word(final["confidence"])


def narration_ok(
    n: Narration | str,
    facts: dict[str, Any],
    final: dict | None = None,
    nf: dict[str, Any] | None = None,
) -> str | None:
    """None if the narration can be used, else why not. With full triage facts the text also
    goes through narration.check_text (banned patterns, 200 words, the closing rating sentence,
    the open-cause rule). A plain string with minimal facts is checked for length, score and
    Double-check only."""
    text = n if isinstance(n, str) else n.text
    t = facts["triage"]
    words = narration.word_count(text)
    if words > MAX_WORDS:
        return f"{words} words > {MAX_WORDS}"
    s = t["score"]
    if not re.search(rf"\b({round(s)}|{s:.1f})\b", text):
        return "the trust score is missing"
    status = fallbacks.narration_status(final)
    if final and final.get("disagreement") and "double-check" not in text.lower():
        return "a Disagreement must end with 'Double-check: ...'"
    if final and final.get("cause_status") == "open" and "double-check" not in text.lower():
        return "an open cause must give 'Double-check: ...'"
    if nf is None and "site" in t:
        nf = narration.narration_facts(facts, (facts.get("event_context") or {}).get("items"))
    if nf is not None:
        if bad := narration.check_text(text, nf, status):
            return bad
    elif status == "open" and (m := fallbacks.MECHANISM_WORDS.search(text)):
        return f"an open cause must not name a mechanism ('{m.group(0)}')"
    if isinstance(n, str):
        return None
    for field in ("direction", "confidence_word", "cause_or_disagreement", "action"):
        if not getattr(n, field).strip():
            return f"field {field} is empty"
    if n.direction.strip() != t["direction_phrase"] or t["direction_phrase"] not in text:
        return f"direction must be '{t['direction_phrase']}' and appear verbatim in the text"
    closing = nf["rating_sentence"] if nf else t["score_display"]
    if n.score_sentence.strip() != closing or closing not in text:
        return f"score_sentence must be '{closing}' and appear verbatim in the text"
    want = expected_confidence_word(final)
    if n.confidence_word.strip().lower() != want:
        return f"confidence_word must be '{want}'"
    return None


def settle_disagreement(
    v: SkepticVerdict, facts: dict[str, Any], ranking: Ranking, final_pass: bool, meta: dict
) -> SkepticVerdict:
    """On the skeptic's final pass: rule (a) under 0.6 sure + a contradicting control note, or
    rule (b) the change-visit note's cause has the opposite sign to the final cause -> 'disagree'
    with a Disagreement. The note and date are filled from the field notes (verbatim), never
    taken from the model. Not on a final pass, or no grounds -> no Disagreement."""
    conf = (
        v.confidence if v.confidence is not None else fallbacks.skeptic_confidence(facts, ranking)
    )
    rules = fallbacks.disagreement(facts, ranking, conf)
    if not final_pass or rules is None:
        if v.verdict == "disagree" or v.disagreement:
            meta["guard"] = "disagreement dropped: not the final pass, or no contradicting note"
            v = v.model_copy(update={"verdict": "accept", "disagreement": None})
        return v.model_copy(update={"confidence": conf})
    d = rules
    if v.disagreement:  # keep the model's words, but the facts come from the data
        d = rules.model_copy(
            update={
                # rule (b)'s why is the computed note-vs-data sentence; keep it
                "why_they_disagree": (
                    rules.why_they_disagree
                    if rules.rule == "note_sign"
                    else v.disagreement.why_they_disagree or rules.why_they_disagree
                ),
                "recommended_check": v.disagreement.recommended_check or rules.recommended_check,
            }
        )
    return v.model_copy(update={"verdict": "disagree", "confidence": conf, "disagreement": d})


# --------------------------------------------------------------------------- graph


def build_graph(rec: TraceRecorder):
    """Compile the StateGraph. `rec` receives every node's TraceEvents."""

    async def triage(state: AgentState) -> AgentState:
        rec.emit("triage", "started", {})
        t = triage_facts(state["site"])
        route = "narrator" if t["band"] == "Trusted" else "evidence_collector"
        rec.emit("triage", "completed", {**t, "route": route})
        return {
            "facts": {"triage": t},
            "objections": [],
            "rankings": [],
            "usage": [],
            "final": None,
        }

    async def evidence_collector(state: AgentState) -> AgentState:
        rec.emit("evidence_collector", "started", {})
        ev = collect_evidence(state["site"], state["facts"]["triage"])
        for name, out in ev.items():
            rec.emit("evidence_collector", "progress", {"tool": name, "result": out})
        sig = fallbacks.channel_signature(ev["channel_geometry"])
        rec.emit("evidence_collector", "completed", {"tools": list(ev), "channel_signature": sig})
        return {"facts": {**state["facts"], **ev}}

    async def hypothesis_ranker(state: AgentState) -> AgentState:
        facts, objs = state["facts"], state["objections"]
        rnd = len(state["rankings"]) + 1
        rec.emit("hypothesis_ranker", "started", {"round": rnd, "objections_so_far": len(objs)})
        meta: dict[str, Any] = {"model": "fallback"}
        if state["llm"] == "fallback":  # backend is built inside the try below
            r = fallbacks.rank(facts, objs)
        else:
            try:
                r, meta = await llm.structured(
                    "ranker",
                    state["llm"],
                    Ranking,
                    llm.prompt("ranker"),
                    llm.prompt(
                        "ranker_input",
                        # first round blind to channel geometry; after an objection it may see it
                        facts=_dump(_ranker_view(facts, channel=bool(objs))),
                        objections=_dump(objs),
                    ),
                )
                r = clean_ranking(r, facts, objs)
            except Exception as e:  # noqa: BLE001 - any model failure -> rules
                meta = _llm_failed(e)
                r = fallbacks.rank(facts, objs)
        out = r.model_dump()
        rec.emit("hypothesis_ranker", "completed", {"round": rnd, **out, **meta})
        return {
            "ranking": out,
            "rankings": [*state["rankings"], out],
            "usage": [*state["usage"], {"node": "hypothesis_ranker", **meta}],
        }

    async def skeptic(state: AgentState) -> AgentState:
        facts = state["facts"]
        ranking = Ranking.model_validate(state["ranking"])
        rec.emit("skeptic", "started", {"reviewing": ranking.top.cause})
        meta: dict[str, Any] = {"model": "fallback"}
        rules = fallbacks.critique(facts, ranking)
        if state["llm"] == "fallback":  # backend is built inside the try below
            v = rules
        else:
            try:
                v, meta = await llm.structured(
                    "skeptic",
                    state["llm"],
                    SkepticVerdict,
                    llm.prompt("skeptic"),
                    llm.prompt(
                        "skeptic_input",
                        facts=_dump(_ranker_view(facts, channel=False)),
                        channel=_dump(facts.get("channel_geometry")),
                        ranking=_dump(ranking.model_dump()),
                        signature=fallbacks.channel_signature(facts.get("channel_geometry")),
                        objections=_dump(state["objections"]),
                    ),
                )
                # hard guard: a sign contradiction is never accepted
                if v.verdict == "accept" and rules.objection == "sign_mismatch":
                    meta["guard"] = "sign_mismatch overrides the model's accept"
                    v = rules
                # the sign check is arithmetic, not opinion: relabel a wrong 'sign_mismatch'
                elif v.objection == "sign_mismatch" and ranking.top.sign_matches:
                    meta["guard"] = "objection relabelled: the top cause's sign does match"
                    v = v.model_copy(update={"objection": "other"})
            except Exception as e:  # noqa: BLE001
                meta = _llm_failed(e)
                v = rules
        n_obj = len(state["objections"]) + (v.verdict == "object")
        final_pass = not (v.verdict == "object" and n_obj <= MAX_LOOPS)
        v = settle_disagreement(v, facts, ranking, final_pass, meta)
        out = {
            **v.model_dump(),
            "objected_cause": ranking.top.cause if v.verdict == "object" else None,
        }
        objs = state["objections"] + ([out] if v.verdict == "object" else [])
        loop = v.verdict == "object" and len(objs) <= MAX_LOOPS
        rec.emit(
            "skeptic", "completed", {**out, **meta, "loop_back": loop, "objections": len(objs)}
        )
        return {
            "verdict": out,
            "objections": objs,
            "usage": [*state["usage"], {"node": "skeptic", **meta}],
        }

    async def narrator(state: AgentState) -> AgentState:
        facts = state["facts"]
        rec.emit("narrator", "started", {})
        final = None
        if state.get("ranking"):
            r = Ranking.model_validate(state["ranking"])
            verdict = state.get("verdict") or {}
            final = {
                "cause": r.top.cause,
                "confidence": r.top.confidence,
                "first_cause": state["rankings"][0]["hypotheses"][0]["cause"],
                "objections": len(state["objections"]),
                "unresolved": verdict.get("verdict") == "object",
                "skeptic_argument": verdict.get("argument"),
                "skeptic_confidence": verdict.get("confidence"),
                "disagreement": verdict.get("disagreement"),
            }
            notes = facts.get("field_notes", {}).get("distinct_notes") or []
            final["cause_status"] = fallbacks.cause_status(final, notes)
        meta: dict[str, Any] = {"model": "fallback"}
        ctx = (facts.get("event_context") or {}).get("items")
        nf = narration.narration_facts(facts, ctx)
        fb = fallbacks.narrate(facts, final, nf)
        parts, text = fb.model_dump(), fb.text
        if state["llm"] != "fallback":  # backend is built inside the try below
            status = fallbacks.narration_status(final)
            check = parts["action"] if parts["action"].startswith("Double-check") else None
            fixed = narration.sentences(
                nf,
                _cause_label(final),
                status,
                check[len("Double-check: ") :] if check else None,
                _cause_conf(final),
                ((final or {}).get("disagreement") or {}).get("rule"),
                (((final or {}).get("disagreement") or {}).get("best_guess") or {}).get("cause"),
            )
            user = llm.prompt(
                "narrator_input",
                facts=_dump(narrator_view(facts, final, nf)),
                final=_dump(narrator_final(final)),
                sentences=_dump({k: v for k, v in fixed.items() if v}),
            )
            rejected: list[dict[str, str]] = []
            try:
                for attempt in (1, 2):  # a guard hit gets one retry, then the template
                    ask = user
                    if rejected:
                        ask += (
                            "\n\nYour previous text was rejected: "
                            f"{rejected[-1]['why']}. Rewrite it and fix that."
                        )
                    n, meta = await llm.structured(
                        "narrator", state["llm"], Narration, llm.prompt("narrator"), ask
                    )
                    bad = narration_ok(n, facts, final, nf)
                    if not bad:
                        parts, text = n.model_dump(), n.text.strip()
                        break
                    rejected.append({"attempt": attempt, "why": bad, "text": n.text})
                if rejected:
                    meta["attempts"] = rejected
                    if len(rejected) == 2:
                        meta["rejected"] = rejected[-1]["why"]
                        meta["rejected_text"] = rejected[-1]["text"]
            except Exception as e:  # noqa: BLE001
                meta = _llm_failed(e)
                if rejected:
                    meta["attempts"] = rejected
        meta["narration_facts"] = nf
        rec.emit(
            "narrator", "completed", {"narration": text, "parts": parts, "final": final, **meta}
        )
        return {
            "narration": text,
            "final": final,
            "usage": [*state["usage"], {"node": "narrator", **meta}],
        }

    def after_triage(state: AgentState) -> str:
        return "narrator" if state["facts"]["triage"]["band"] == "Trusted" else "evidence_collector"

    def after_skeptic(state: AgentState) -> str:
        v = state["verdict"]
        return (
            "hypothesis_ranker"
            if v["verdict"] == "object" and len(state["objections"]) <= MAX_LOOPS
            else "narrator"
        )

    g = StateGraph(AgentState)
    g.add_node("triage", triage)
    g.add_node("evidence_collector", evidence_collector)
    g.add_node("hypothesis_ranker", hypothesis_ranker)
    g.add_node("skeptic", skeptic)
    g.add_node("narrator", narrator)
    g.add_edge(START, "triage")
    g.add_conditional_edges("triage", after_triage, ["narrator", "evidence_collector"])
    g.add_edge("evidence_collector", "hypothesis_ranker")
    g.add_edge("hypothesis_ranker", "skeptic")
    g.add_conditional_edges("skeptic", after_skeptic, ["hypothesis_ranker", "narrator"])
    g.add_edge("narrator", END)
    return g.compile()


def _ranker_view(facts: dict[str, Any], channel: bool = False) -> dict[str, Any]:
    """Facts for a prompt, minus the per-visit list (notes are summarized). Channel geometry is
    left out unless asked for: it is the skeptic's independent cross-check, so the ranker
    (LLM or rules) reasons from the residual, notes, flood and site facts only."""
    v = dict(facts)
    if not channel:
        v.pop("channel_geometry", None)
    if "field_notes" in v:
        fn = dict(v["field_notes"])
        fn["visits"] = [x for x in fn["visits"] if x["note"] and x["note"].lower() != "clear"]
        v["field_notes"] = fn
    return v


async def run_agents(
    site: str,
    llm_mode: str | None = None,
    queue: asyncio.Queue | None = None,
    trace_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the team on one gauge. Returns the final state plus trace path and totals."""
    m = llm.mode(llm_mode)
    rec = TraceRecorder(site, m, queue, trace_dir)
    t0 = time.perf_counter()
    rec.emit("run", "started", {"llm": m})
    try:
        state = await build_graph(rec).ainvoke({"site": site, "llm": m}, {"recursion_limit": 25})
    except Exception as e:
        rec.emit("run", "error", {"error": f"{type(e).__name__}: {e}"[:500]})
        raise
    usage = state.get("usage", [])
    totals = {
        "input_tokens": sum(u.get("input_tokens", 0) for u in usage),
        "output_tokens": sum(u.get("output_tokens", 0) for u in usage),
        "llm_calls": sum(1 for u in usage if u.get("model") != "fallback"),
        "fallbacks_used": sum(1 for u in usage if "llm_error" in u or "rejected" in u),
        "wall_seconds": round(time.perf_counter() - t0, 2),
    }
    rec.final = {"narration": state.get("narration"), "final": state.get("final"), **totals}
    rec.emit("run", "completed", rec.final)
    return {**state, "trace_path": str(rec.path), "run_id": rec.run_id, "totals": totals}


def run_sync(
    site: str, llm_mode: str | None = None, trace_dir: Path | None = None
) -> dict[str, Any]:
    return asyncio.run(run_agents(site, llm_mode, None, trace_dir))
