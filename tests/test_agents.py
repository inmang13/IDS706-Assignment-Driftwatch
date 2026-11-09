"""M2 agent team, LLM=fallback, offline."""

import re

import pytest

from driftwatch.agents import fallbacks, graph, llm, narration, tools
from driftwatch.agents.models import (
    BestGuess,
    Disagreement,
    FieldNoteRef,
    Hypothesis,
    Narration,
    Ranking,
    SkepticVerdict,
)
from driftwatch.agents.trace import TraceRecorder, load_trace, replay
from driftwatch.modules.rating_curve import causes

HEPCO, NEWPORT, ASHEVILLE, SWANNANOA = "03459500", "03455000", "03451500", "03451000"
MILLS = "03446000"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    d = tmp_path_factory.mktemp("traces")
    return {s: graph.run_sync(s, "fallback", d) for s in (HEPCO, NEWPORT, ASHEVILLE, SWANNANOA)}


@pytest.fixture(scope="module")
def asheville_open(tmp_path_factory):
    """Asheville with rule (b) switched off: the open-cause example (scour ranked, no note backs
    it). With rule (b) on, its 'Debris - Light' change-visit note makes it a Disagreement."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fallbacks, "note_at_change", lambda facts: None)
        return graph.run_sync(ASHEVILLE, "fallback", tmp_path_factory.mktemp("open"))


def test_graph_compiles(tmp_path):
    g = graph.build_graph(TraceRecorder("x", "fallback", out_dir=tmp_path))
    assert set(g.get_graph().nodes) >= {
        "triage",
        "evidence_collector",
        "hypothesis_ranker",
        "skeptic",
        "narrator",
    }


def test_hepco_skeptic_objects_and_final_is_not_plain_scour(runs):
    r = runs[HEPCO]
    assert len(r["objections"]) >= 1
    assert r["objections"][0]["objection"] == "channel_evidence"
    assert r["final"]["cause"] != "scour"


def test_newport_is_fill(runs):
    assert runs[NEWPORT]["final"]["cause"] == "fill"


def test_asheville_is_a_positive_sign_cause(runs):
    assert causes.get_cause(runs[ASHEVILLE]["final"]["cause"]).expected_sign == "positive"


def test_swannanoa_goes_straight_to_narrator_with_no_cause(runs):
    r = runs[SWANNANOA]
    assert r["final"] is None
    nodes = [e.node for e in replay(r["trace_path"])]
    assert "evidence_collector" not in nodes and "skeptic" not in nodes
    assert "94" in r["narration"]


def test_ranker_always_lists_datum_change_and_inconclusive(runs):
    for s in (HEPCO, NEWPORT, ASHEVILLE):
        for rk in runs[s]["rankings"]:
            keys = {h["cause"] for h in rk["hypotheses"]}
            assert {"datum_change", "inconclusive"} <= keys


def test_narrations_are_short_and_carry_the_score(runs):
    for r in runs.values():
        assert graph.narration_ok(r["narration"], r["facts"]) is None


def _stable(events):
    vol = {"wall_seconds", "seconds"}
    return [
        (e.seq, e.node, e.status, {k: v for k, v in e.payload.items() if k not in vol})
        for e in events
    ]


def test_replay_determinism(tmp_path):
    out = graph.run_sync(HEPCO, "fallback", tmp_path)
    replayed = list(replay(out["trace_path"]))
    assert replayed[0].node == "run" and replayed[-1].node == "run"
    assert replayed[-1].status == "completed"
    assert [e["seq"] for e in load_trace(out["trace_path"])["events"]] == list(range(len(replayed)))
    # replaying twice gives identical events
    assert list(replay(out["trace_path"])) == replayed
    # a second fallback run gives the same event stream (minus timing)
    out2 = graph.run_sync(HEPCO, "fallback", tmp_path)
    assert out2["trace_path"] != out["trace_path"]
    assert _stable(replay(out2["trace_path"])) == _stable(replayed)


def test_channel_geometry_hepco_shows_speed_falling_more_than_area():
    ch = tools.channel_geometry_trend(HEPCO, "2024-12-17T18:18:38+00:00")
    assert ch["sufficient"] and ch["n_after"] >= 10
    assert ch["velocity_change_pct"] < ch["area_change_pct"] < 0
    assert fallbacks.channel_signature(ch) == "backwater"


def test_channel_geometry_insufficient_when_split_is_too_late():
    ch = tools.channel_geometry_trend(HEPCO, "2026-10-10")
    assert ch["sufficient"] is False and ch["area_change_pct"] is None


def test_flood_context_asheville_gap_is_empty_and_hepco_spans_helene():
    a = tools.flood_context(ASHEVILLE, "2025-07-23T17:37:24+00:00")
    assert a["peak"] is None and a["helene_in_gap"] is False
    h = tools.flood_context(HEPCO, "2024-12-17T18:18:38+00:00")
    assert h["helene_in_gap"] is True


def test_field_notes_include_hepco_scour_note():
    assert "Scour control changed" in tools.field_notes(HEPCO)["distinct_notes"]


def test_clean_ranking_adds_required_and_drops_duplicates():
    facts = {"triage": graph.triage_facts(HEPCO)}
    facts.update(graph.collect_evidence(HEPCO, facts["triage"]))
    r = Ranking(
        hypotheses=[
            Hypothesis(cause="fill", confidence=0.7, sign_matches=False),
            Hypothesis(cause="fill", confidence=0.1, sign_matches=True),
            Hypothesis(cause="scour", confidence=0.2, sign_matches=True),
        ]
    )
    c = graph.clean_ranking(r, facts, [])
    keys = [h.cause for h in c.hypotheses]
    assert keys.count("fill") == 1 and {"datum_change", "inconclusive"} <= set(keys)
    assert {h.cause: h.sign_matches for h in c.hypotheses}["scour"] is False  # recomputed
    assert c.top.cause == "fill"


def test_narration_guard():
    facts = {"triage": {"score": 24.0}}
    assert graph.narration_ok("word " * (graph.MAX_WORDS + 1) + "24", facts)
    assert graph.narration_ok("Trust score 30/100.", facts) == "the trust score is missing"
    assert graph.narration_ok("Trust score 24/100 (Stale).", facts) is None


def test_llm_failure_falls_back_and_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "backend", lambda role, mode: (object(), "fake"))

    async def boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(llm, "structured", boom)
    out = graph.run_sync(HEPCO, "gemini", tmp_path)
    assert out["final"]["cause"] != "scour"
    assert out["totals"]["fallbacks_used"] >= 3
    errs = [
        e.payload.get("llm_error") for e in replay(out["trace_path"]) if e.status == "completed"
    ]
    assert any(e and "model down" in e for e in errs)


def test_skeptic_loop_is_bounded(monkeypatch, tmp_path):
    always = SkepticVerdict(
        verdict="object", objection="other", argument="no", suggested_cause="inconclusive"
    )
    monkeypatch.setattr(fallbacks, "critique", lambda facts, ranking: always)
    # a Disagreement would replace the last objection; switch it off to test the bound alone
    monkeypatch.setattr(fallbacks, "disagreement", lambda facts, ranking, conf: None)
    out = graph.run_sync(HEPCO, "fallback", tmp_path)
    assert len(out["objections"]) == graph.MAX_LOOPS + 1
    assert len(out["rankings"]) == graph.MAX_LOOPS + 1
    assert out["final"]["unresolved"] is True


def test_llm_mode_rejects_unknown():
    with pytest.raises(ValueError):
        llm.mode("gpt")


def test_wrong_sign_mismatch_label_is_relabelled(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "backend", lambda role, mode: (object(), "fake"))

    async def fake(role, mode, schema, system, user):
        if schema is SkepticVerdict:
            v = SkepticVerdict(
                verdict="object", objection="sign_mismatch", argument="x", suggested_cause="fill"
            )
            return v, {"model": "fake"}
        raise RuntimeError("use the rules")

    monkeypatch.setattr(llm, "structured", fake)
    out = graph.run_sync(HEPCO, "gemini", tmp_path)
    first = out["objections"][0]
    assert first["objection"] == "other"  # datum_change fits either sign
    guards = [e.payload.get("guard") for e in replay(out["trace_path"]) if e.node == "skeptic"]
    assert any(g and "relabelled" in g for g in guards)


def test_queue_receives_the_same_events_as_the_trace(tmp_path):
    import asyncio

    async def go():
        q = asyncio.Queue()
        out = await graph.run_agents(SWANNANOA, "fallback", q, tmp_path)
        got = []
        while not q.empty():
            got.append(q.get_nowait())
        return out, got

    out, got = asyncio.run(go())
    assert got == list(replay(out["trace_path"]))
    assert [e.seq for e in got] == list(range(len(got)))


# --- direction words, Disagreement, replay default ------------------------------------------


def test_direction_phrase_reaches_fallback_and_llm_input(runs):
    for s, phrase in ((HEPCO, "below the rating"), (ASHEVILLE, "above the rating")):
        facts = runs[s]["facts"]
        assert facts["triage"]["direction_phrase"] == phrase
        assert phrase in runs[s]["narration"]  # fallback narrator used it
        view = graph.narrator_view(facts)
        assert view["direction_phrase"] == phrase
        assert "recent_median_residual_pct" not in view and "direction" not in view
        rendered = llm.prompt("narrator_input", facts=graph._dump(view), final="null")
        assert phrase in rendered
    assert "above the rating" in runs[SWANNANOA]["narration"]


def test_hepco_fallback_disagrees_and_newport_does_not(runs):
    h = runs[HEPCO]
    assert h["verdict"]["verdict"] == "disagree"
    d = h["final"]["disagreement"]
    assert d["field_note"] == {"note": "Scour control changed", "date": "2024-12-17"}
    assert d["best_guess"]["confidence"] < fallbacks.DISAGREE_BELOW
    assert d["recommended_check"] and d["why_they_disagree"]
    assert "Double-check:" in h["narration"]
    ev = [e for e in replay(h["trace_path"]) if e.node == "skeptic" and e.status == "completed"]
    assert ev[-1].payload["disagreement"]["field_note"]["note"] == "Scour control changed"
    n = runs[NEWPORT]
    assert n["verdict"]["verdict"] == "accept" and n["final"]["disagreement"] is None
    assert "Skeptic under 60 %" not in n["narration"]  # no Disagreement sentence for Newport


def test_narration_guard_requires_double_check_for_disagreement():
    facts = {"triage": {"score": 24.0}}
    final = {"disagreement": {"x": 1}}
    assert graph.narration_ok("Trust score 24/100.", facts, final)
    assert graph.narration_ok("Double-check: levels. Trust score 24/100.", facts, final) is None


def test_ranker_sees_channel_only_after_an_objection():
    facts = {"triage": {}, "channel_geometry": {"a": 1}, "field_notes": {"visits": []}}
    assert "channel_geometry" not in graph._ranker_view(facts)
    assert "channel_geometry" in graph._ranker_view(facts, channel=True)


def test_replay_default_file_wins_over_newest(tmp_path):
    import json

    from driftwatch.agents.trace import latest_trace

    (tmp_path / "03459500-20260101T000000000000Z.json").write_text("{}")
    (tmp_path / "03459500-20270101T000000000000Z.json").write_text("{}")
    assert latest_trace(HEPCO, tmp_path).name.startswith("03459500-2027")
    (tmp_path / "replay_defaults.json").write_text(
        json.dumps({HEPCO: "03459500-20260101T000000000000Z.json"})
    )
    assert latest_trace(HEPCO, tmp_path).name.startswith("03459500-2026")


def test_missing_credentials_degrade_to_rules_with_a_warning(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    out = graph.run_sync(HEPCO, "gemini", tmp_path)  # must not raise
    assert out["totals"]["fallbacks_used"] >= 3 and out["totals"]["llm_calls"] == 0
    warns = [e.payload.get("warning") for e in replay(out["trace_path"]) if e.status == "completed"]
    assert any(w and "GOOGLE_CLOUD_PROJECT is not set" in w for w in warns)
    assert out["final"]["cause"] != "scour"


def test_fallback_ranker_scores_insufficient_data_with_few_visits():
    facts = {"triage": graph.triage_facts(HEPCO)}
    facts.update(graph.collect_evidence(HEPCO, facts["triage"]))
    assert "insufficient_data" not in {h.cause for h in fallbacks.rank(facts).hypotheses}
    facts["triage"] = {**facts["triage"], "n_visits_last_12_months": 2}
    hyps = {h.cause: h for h in fallbacks.rank(facts).hypotheses}
    assert hyps["insufficient_data"].confidence > 0
    assert hyps["insufficient_data"].sign_matches


# --- structured narration (B), narrator facts (C), Disagreement parity (E) -----------------


def _rating(t):
    return f"Rating confidence {round(t['score'])}/100 ({t['band']})."


def _facts(site):
    f = {"triage": graph.triage_facts(site)}
    if f["triage"]["band"] != "Trusted":
        f.update(graph.collect_evidence(site, f["triage"]))
    return f


def test_fallback_narration_passes_the_structured_guard(runs):
    for r in runs.values():
        parts = [e for e in replay(r["trace_path"]) if e.node == "narrator"][-1].payload["parts"]
        n = Narration.model_validate(parts)
        assert graph.narration_ok(n, r["facts"], r["final"]) is None
        assert n.direction == r["facts"]["triage"]["direction_phrase"]


def test_llm_narration_with_wrong_direction_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(llm, "backend", lambda role, mode: (object(), "fake"))
    facts = _facts(SWANNANOA)

    async def fake(role, mode, schema, system, user):
        if schema is Narration:
            t = facts["triage"]
            n = Narration(
                direction="below the rating",  # wrong: Swannanoa sits above
                confidence_word="n/a",
                cause_or_disagreement="No shift.",
                action="Keep visiting.",
                score_sentence=_rating(t),
                text=f"Measurements sit 7 % below the rating. {_rating(t)}",
            )
            return n, {"model": "fake"}
        raise RuntimeError("rules")

    monkeypatch.setattr(llm, "structured", fake)
    out = graph.run_sync(SWANNANOA, "gemini", tmp_path)
    ev = [e for e in replay(out["trace_path"]) if e.node == "narrator"][-1].payload
    assert "direction must be" in ev["rejected"]
    assert "above the rating" in out["narration"]  # fell back to the template


def test_narrator_view_has_trusted_facts_and_no_signed_numbers():
    v = graph.narrator_view(_facts(SWANNANOA))
    for k in ("days_since_last_visit", "n_visits_last_12_months", "latest_control_note"):
        assert k in v
    assert v["recent_median_residual"].endswith("above the rating")
    assert "score_deductions" not in v and "recent_median_residual_pct" not in v
    prompt = llm.prompt("narrator").lower()
    assert "do not mention anything not in facts" in prompt
    assert "do not describe mechanisms" in prompt


def test_fallback_and_llm_disagreements_share_one_type(monkeypatch, tmp_path):
    fb = graph.run_sync(HEPCO, "fallback", tmp_path)
    monkeypatch.setattr(llm, "backend", lambda role, mode: (object(), "fake"))

    async def fake(role, mode, schema, system, user):
        # second review (an objection is on file): the LLM disagrees in its own words
        if schema is SkepticVerdict and '"verdict": "object"' in user:
            d = Disagreement(
                best_guess=BestGuess(cause="fill", confidence=0.3),
                field_note=FieldNoteRef(note="made up", date="1999-01-01"),
                why_they_disagree="LLM words.",
                recommended_check="LLM check.",
            )
            v = SkepticVerdict(verdict="disagree", argument="x", confidence=0.3, disagreement=d)
            return v, {"model": "fake"}
        raise RuntimeError("rules")

    monkeypatch.setattr(llm, "structured", fake)
    lm = graph.run_sync(HEPCO, "gemini", tmp_path)
    a, b = fb["final"]["disagreement"], lm["final"]["disagreement"]
    assert Disagreement.model_validate(a) and Disagreement.model_validate(b)
    assert set(a) == set(b)
    # the note and date always come from the field records, never from the model
    assert (
        b["field_note"]
        == a["field_note"]
        == {
            "note": "Scour control changed",
            "date": "2024-12-17",
        }
    )
    # rule (b) holds for Hepco: why is the computed note-vs-data sentence; check is the LLM's
    assert b["rule"] == a["rule"] == "note_sign"
    assert b["why_they_disagree"] == a["why_they_disagree"]
    assert b["recommended_check"] == "LLM check."


def test_cause_status_open_for_asheville_corroborated_for_newport(runs, asheville_open):
    # rule (b) counts only 'control changed' notes, so Asheville's "Debris - Light" doesn't
    assert runs[ASHEVILLE]["final"]["cause_status"] == "open"  # scour, only Debris notes
    assert asheville_open["final"]["cause_status"] == "open"
    assert runs[NEWPORT]["final"]["cause_status"] == "corroborated"  # "Fill control changed"
    assert runs[HEPCO]["final"]["cause_status"] == "disagreement"


def test_open_cause_narration_names_no_mechanism(asheville_open):
    r = asheville_open
    text = r["narration"]
    assert "Double-check:" in text and fallbacks.OPEN_CHECK in text
    assert r["facts"]["triage"]["direction_phrase"] in text
    nf = narration.narration_facts(r["facts"])
    assert fallbacks.MECHANISM_WORDS.search(narration.strip_labelled(text, nf)) is None


def test_open_cause_hides_the_cause_from_the_narrator(runs, asheville_open):
    r = asheville_open
    seen = graph.narrator_final(r["final"])
    assert seen == {"cause_status": "open", "recommended_check": fallbacks.OPEN_CHECK}
    assert graph.narrator_view(r["facts"], r["final"])["cause_status"] == "open"
    assert graph.narrator_final(runs[NEWPORT]["final"])["cause"] == "fill"


def test_llm_open_narration_naming_a_cause_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(fallbacks, "note_at_change", lambda facts: None)  # keep it open
    monkeypatch.setattr(llm, "backend", lambda role, mode: (object(), "fake"))
    facts = _facts(ASHEVILLE)

    async def fake(role, mode, schema, system, user):
        if schema is Narration:
            assert '"cause_status": "open"' in user and "scour" not in user.lower()
            t = facts["triage"]
            text = (
                f"Recent field measurements sit 41 % {t['direction_phrase']}. This shift is "
                f"likely due to scour. Double-check: {fallbacks.OPEN_CHECK} {_rating(t)}"
            )
            n = Narration(
                direction=t["direction_phrase"],
                confidence_word="uncertain",
                cause_or_disagreement="Likely due to scour.",
                action=f"Double-check: {fallbacks.OPEN_CHECK}",
                score_sentence=_rating(t),
                text=text,
            )
            return n, {"model": "fake"}
        raise RuntimeError("rules")

    monkeypatch.setattr(llm, "structured", fake)
    out = graph.run_sync(ASHEVILLE, "gemini", tmp_path)
    ev = [e for e in replay(out["trace_path"]) if e.node == "narrator"][-1].payload
    assert "must not name a mechanism" in ev["rejected"]
    nf = narration.narration_facts(out["facts"])
    assert fallbacks.MECHANISM_WORDS.search(narration.strip_labelled(out["narration"], nf)) is None


# --- report-voice narration: computed facts, rules (1)-(7), guard, retry, cached leads -----

STALE3 = (NEWPORT, HEPCO, ASHEVILLE)


def _nf(r):
    return narration.narration_facts(r["facts"])


@pytest.mark.parametrize("site", STALE3)
def test_narration_rules_hold_for_the_fallback(runs, site):
    r = runs[site]
    text, nf = r["narration"], _nf(r)
    assert "Q = V × A" not in text  # (1) dropped: the opener was filler (Grace)
    assert "same flow" not in text and "speed" not in text
    assert nf["note"] and nf["note"]["meaning"] in text  # (2) the fixed note meaning, verbatim
    assert "After the change, at that stage, area" in text  # (3)
    assert re.search(r"[+\u2212-]\d+ %", text) is None  # directions in words, no signed numbers
    assert f"at a stage of {nf['at_stage_ft']:.2f} ft" in text  # ... named in the level sentence
    assert re.search(r"so the flow rate there (rose|fell) about \d+ %", text)
    # (4) Helene only when it falls between the last visit and the change visit
    assert nf["helene"] is (site != ASHEVILLE)
    assert ("Hurricane Helene (2024-09-27) passed between" in text) is nf["helene"]
    low = text.lower()
    assert "the team" not in low and "amount of water" not in low  # (5)
    assert narration.word_count(text) <= narration.MAX_WORDS  # (6)
    assert text.endswith(f"Rating confidence {round(r['facts']['triage']['score'])}/100 (Stale).")
    assert narration.banned(text) is None  # (7)
    assert narration.check_text(text, nf, fallbacks.narration_status(r["final"])) is None


def test_newport_facts_and_sentences(runs):
    r = runs[NEWPORT]
    nf, text = _nf(r), r["narration"]
    assert nf["change_date"] == "2024-10-28"
    assert nf["level_change_ft"] == 0.71 and nf["level_word"] == "higher"
    assert "For a given flow rate, the river stands 0.71 ft higher than the curve" in text
    assert nf["at_stage_ft"] == 2.7  # channel_geometry_trend's at_stage_ft
    assert nf["flow_change_pct"] == -42 and nf["flow_change_cfs"] < 0
    # (1 + 0.252) x (1 - 0.583) - 1 = -47.8 %: same sign, 5.6 points from -42.2 -> agrees
    assert nf["check_pct"] == pytest.approx(-47.8, abs=0.2) and nf["check_agrees"] is True
    assert "at that stage, area rose 25 % and velocity fell 58 %" in text
    assert "so the flow rate there fell about 48 %" in text
    assert "which agrees with the 42 % drop in measured flow rate" in text
    assert nf["note"]["note"] == "Fill control changed" and nf["note"]["agrees_with_data"]
    assert "disagrees with the data" not in text
    assert nf["helene"] is True  # 2024-08-19 < 2024-09-27 < 2024-10-28 (the change visit)
    assert (
        "Hurricane Helene (2024-09-27) passed between the 2024-08-19 and 2024-10-28 visits; the "
        "storm gaugings were rated Poor, the largest 91,700 cfs on 2024-09-28."
    ) in text
    assert "DriftWatch's agents" in text


def test_hepco_note_disagrees_and_no_measured_flood(runs):
    r = runs[HEPCO]
    nf, text = _nf(r), r["narration"]
    assert nf["note"]["note"] == "Scour control changed"
    assert nf["note"]["agrees_with_data"] is False and "That disagrees with the data." in text
    assert "0.33 ft higher than the curve predicts" in text
    assert nf["check_agrees"] is True and "which agrees with the 26 % drop" in text
    assert "area fell 11 % and velocity fell 22 %" in text
    assert (
        "Hurricane Helene (2024-09-27) passed between the 2024-08-22 and 2024-12-17 visits; no "
        "gauging was made during the storm."
    ) in text
    assert "the hydrographer's note says scour; the two disagree" in text
    assert "Double-check:" in text


def test_asheville_check_does_not_back_up_and_conclusion_stays_open(asheville_open):
    r = asheville_open
    nf, text = _nf(r), r["narration"]
    assert nf["level_word"] == "lower" and "0.27 ft lower than the curve predicts" in text
    # (1.077)(1.017) - 1 = +9.5 % vs a +46.2 % step: 37 points apart -> does not back up
    assert nf["check_agrees"] is False and "which does not back up the 46 % rise" in text
    assert "area rose 8 % and velocity rose 2 %" in text
    assert "That disagrees with the data." in text  # Debris raises the level; data sit above
    assert "no measured high flow explains it" in text
    # open cause: outside the labelled note sentences, no mechanism word
    assert fallbacks.MECHANISM_WORDS.search(narration.strip_labelled(text, nf)) is None
    assert fallbacks.MECHANISM_WORDS.search(text)  # ... the note itself does carry one


def test_helene_old_window_case_and_check_threshold_on_synthetic_shift(runs):
    """The old rule (change date within 30 days after 2024-09-27). A change dated 23 days after
    the storm used to count by date alone; under the visit rule it counts only if it was first
    measured at the first visit after the storm, and 2024-10-20 is not that visit (2024-10-28)."""
    facts = {**runs[NEWPORT]["facts"]}
    t = dict(facts["triage"])
    t["top_shift"] = {**t["top_shift"], "time": "2024-10-20T12:00:00Z"}  # 23 days after
    facts["triage"] = t
    nf = narration.narration_facts(facts)
    assert nf["helene"] is False  # old rule: True
    s = narration.sentences(nf, "fill / aggradation", "corroborated", "Survey it.", 0.44)
    assert "Helene" not in s["event"]
    t["top_shift"] = {**t["top_shift"], "time": "2024-10-28T20:03:25Z", "size_pct": -20.0}
    nf = narration.narration_facts(facts)
    assert nf["helene"] is True  # old rule: False (31 days after 2024-09-27)
    assert nf["check_agrees"] is False  # -47.8 vs -20.0: 27.8 points apart
    t["top_shift"] = {**t["top_shift"], "size_pct": 30.0}
    assert narration.narration_facts(facts)["check_agrees"] is False  # opposite sign


END = " Rating confidence 24/100 (Stale)."
BAD_SAMPLES = [
    "The gauge drifted — badly." + END,
    "The gauge drifted – badly." + END,
    "This is not just drift." + END,
    "It is not scour, but fill." + END,
    "Overall, the rating is off." + END,
    "Notably, the rating is off." + END,
    "This is a crucial finding." + END,
    "We delve into the residuals." + END,
    "The rating is off!" + END,
    "Why did the rating drift?" + END,
    "The flood was historic, dramatic, and catastrophic." + END,
    "The team found fill." + END,
    "The amount of water fell." + END,
    "**Finding:** drift." + END,
    "The river rose 0.33ft for a given flow rate." + END,
    "The river stands higher for the same flow." + END,
    "Water speed fell." + END,
    "Area changed -11 % at the gauge." + END,
    "Flow rose by +440 cfs." + END,
]


def test_banned_pattern_check_passes_fallbacks_and_rejects_bad_samples(runs):
    for s in STALE3:
        assert narration.banned(runs[s]["narration"]) is None, s
    for bad in BAD_SAMPLES:
        assert narration.banned(bad), bad
    # a deliberately bad full narration: right facts, wrong voice
    nf = _nf(runs[HEPCO])
    bad = runs[HEPCO]["narration"].replace(". For a given", " — and, importantly, for a given")
    assert narration.check_text(bad, nf, "disagreement")
    # a moral after the rating sentence is rejected too
    moral = runs[HEPCO]["narration"] + " Care."
    assert "must end with" in narration.check_text(moral, nf, "disagreement")


def test_guard_holds_open_cause_rule_outside_the_note(asheville_open):
    r = asheville_open
    nf, text = _nf(r), r["narration"]
    assert narration.check_text(text, nf, "open") is None
    worse = text.replace("so the cause remains open.", "so scour is likely.")
    assert "must not name a mechanism" in narration.check_text(worse, nf, "open")


def _llm_narration(r, text):
    t = r["facts"]["triage"]
    return Narration(
        direction=t["direction_phrase"],
        confidence_word=graph.expected_confidence_word(r["final"]),
        cause_or_disagreement="x",
        action="Double-check: x",
        score_sentence=_rating(t),
        text=text,
    )


@pytest.mark.parametrize("bad_times", [1, 2])
def test_narrator_retries_once_then_uses_the_template(runs, monkeypatch, tmp_path, bad_times):
    r = runs[HEPCO]
    good = r["narration"].replace("Since the 2024-12-17 visit,", "Since 2024-12-17,")
    bad = r["narration"].replace(". For a given", " — for a given")
    assert good != r["narration"] and bad != r["narration"]
    calls = []
    monkeypatch.setattr(llm, "backend", lambda role, mode: (object(), "fake"))

    async def fake(role, mode, schema, system, user):
        if schema is Narration:
            calls.append(user)
            text = bad if len(calls) <= bad_times else good
            return _llm_narration(r, text), {"model": "fake"}
        raise RuntimeError("rules")

    monkeypatch.setattr(llm, "structured", fake)
    out = graph.run_sync(HEPCO, "gemini", tmp_path)
    ev = [e for e in replay(out["trace_path"]) if e.node == "narrator"][-1].payload
    assert len(calls) == 2 and "previous text was rejected" in calls[1]
    assert ev["attempts"][0]["why"].startswith("dash used as punctuation")
    if bad_times == 1:
        assert out["narration"] == good and "rejected" not in ev
    else:
        assert out["narration"] == r["narration"] and ev["rejected"]


def test_cached_lead_reaches_narration_and_trace(monkeypatch, tmp_path):
    import json

    from driftwatch.agents import context

    url = "https://example.org/pigeon-river-bridge"
    doc = {
        "site": MILLS,
        "items": [
            {
                "kind": "construction",
                "claim": "NCDOT replaced a bridge over the Mills River in Henderson County.",
                "date": "2024-11",
                "url": url,
                "source_title": "NCDOT project page",
                "retrieved_at": "2026-11-07T00:00:00Z",
            },
            {"kind": "other", "claim": "No URL here.", "url": None, "source_title": "x"},
        ],
    }
    (tmp_path / f"{MILLS}.json").write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(context, "CONTEXT_DIR", tmp_path)
    assert len(context.load(MILLS)["items"]) == 1  # items without a URL are dropped
    # Mills: the three Stale narrations run ~195 words, so the template drops a lead there
    out = graph.run_sync(MILLS, "fallback", tmp_path / "tr")
    text = out["narration"]
    assert "Possible lead: NCDOT replaced a bridge" in text and "(NCDOT project page)." in text
    assert narration.word_count(text) <= narration.MAX_WORDS
    nf = narration.narration_facts(out["facts"], out["facts"]["event_context"]["items"])
    assert narration.check_text(text, nf, fallbacks.narration_status(out["final"])) is None
    ev = [e for e in replay(out["trace_path"]) if e.node == "evidence_collector"]
    assert any(url in json.dumps(e.payload) for e in ev)


def test_no_context_file_means_no_lead(runs):
    for s in STALE3:
        assert runs[s]["facts"]["event_context"] is None
        assert "Possible lead" not in runs[s]["narration"]


def test_pick_lead_prefers_construction_and_skips_helene_outside_the_window():
    def item(kind, claim, title="Some page"):
        return {"kind": kind, "claim": claim, "url": "https://x.org", "source_title": title}

    items = [
        item("storm", "Hurricane Helene flooded the Pigeon River."),
        item("storm", "A storm flooded Haywood County."),
        item("construction", "Crews built a causeway in the Pigeon River."),
        item("construction", "Crews are — maybe — building."),  # would trip the guard
    ]
    assert narration.pick_lead(items, helene=False)["claim"].startswith("Crews built")
    assert (
        narration.pick_lead(items[:2], helene=False)["claim"] == "A storm flooded Haywood County."
    )
    assert narration.pick_lead(items[:1], helene=False) is None
    assert narration.pick_lead(items[:1], helene=True) is not None
    assert narration.pick_lead(None, helene=False) is None


def test_helene_visit_rule():
    hb = narration.helene_between
    assert hb("2024-08-22", "2024-12-17", "2024-12-17")  # Hepco: storm between, change visit
    assert hb("2024-08-19", "2024-10-28", "2024-10-28")  # Newport
    assert not hb("2025-06-03", "2025-07-23", "2025-07-23")  # Asheville: both after
    assert not hb("2024-09-30", "2024-11-05", "2024-11-05")  # last visit already after the storm
    assert not hb("2024-08-01", "2024-09-20", "2024-09-20")  # change visit before the storm
    assert not hb("2024-08-19", "2024-10-28", "2024-12-01")  # change not at the first visit after
    assert not hb(None, "2024-10-28", "2024-10-28") and not hb("2024-08-19", None, None)


def test_helene_event_sentence_without_a_storm_gauging(runs):
    nf = {**_nf(runs[NEWPORT]), "flood": None}
    s = narration.sentences(nf, "fill / aggradation", "corroborated", "Survey it.", 0.44)
    assert s["event"] == (
        "Hurricane Helene (2024-09-27) passed between the 2024-08-19 and 2024-10-28 visits; no "
        "gauging was made during the storm."
    )
    nf["flood"] = {
        "date": "2024-10-01",
        "discharge_cfs": 12345,
        "rated": "Fair",
        "storm_gauging": False,
    }
    s = narration.sentences(nf, "fill / aggradation", "corroborated", "Survey it.", 0.44)
    assert "no gauging was made during the storm" in s["event"] and "12,300 cfs" in s["event"]


def test_guard_rejects_helene_outside_the_window(runs):
    r = runs[ASHEVILLE]
    nf = _nf(r)
    text = r["narration"].replace(
        "No gauging falls", "Hurricane Helene struck earlier. No gauging falls"
    )
    assert "Helene may be named only" in narration.check_text(text, nf, "open")
    hepco = runs[HEPCO]["narration"].replace(
        "Hurricane Helene (2024-09-27) passed", "A storm passed"
    )
    assert "verbatim" in narration.check_text(hepco, _nf(runs[HEPCO]), "disagreement")


def test_context_text_hygiene():
    from driftwatch.agents import context

    assert context.clean_text("Bridge 142 — I-40 (2024–2025) | NCDOT?") == (
        "Bridge 142, I-40 2024-2025 NCDOT"
    )
    assert context.clean_title("I-40 Pigeon River Gorge reopens - Smoky Mountain News") == (
        "I-40 Pigeon River Gorge reopens"
    )
    assert context.clean_title("Pigeon River | American Whitewater") == "Pigeon River"


def test_guard_requires_q_sentence_check_verdict_and_event_wording(runs):
    h, n, a = runs[HEPCO], runs[NEWPORT], runs[ASHEVILLE]
    nfh, nfn, nfa = _nf(h), _nf(n), _nf(a)
    flipped = h["narration"].replace("which agrees with", "which matches")
    assert "which agrees with" in narration.check_text(flipped, nfh, "disagreement")
    vague = a["narration"].replace("so no measured high flow explains it", "so nothing shows")
    assert "no measured high flow" in narration.check_text(vague, nfa, "disagreement")
    no_peak = n["narration"].replace("91,700 cfs", "a big flow")
    assert "verbatim" in narration.check_text(no_peak, nfn, "corroborated")  # Helene sentence


def test_pick_lead_skips_unreviewed_and_old_usgs_reports():
    def item(kind, date, **kw):
        return {
            "kind": kind,
            "date": date,
            "claim": f"A {kind} item on the Pigeon River.",
            "url": "https://x.org",
            "source_title": "Page",
            **kw,
        }

    assert narration.pick_lead([item("usgs_report", "2014-12")], helene=False) is None
    assert narration.pick_lead([item("usgs_report", "1961")], helene=False) is None
    assert narration.pick_lead([item("usgs_report", "2015")], helene=False)["date"] == "2015"
    assert narration.pick_lead([item("usgs_report", "")], helene=False) is not None  # undated
    assert (
        narration.pick_lead([item("storm", "1940-08-30")], helene=False) is not None
    )  # only reports
    bad = item("dam", "2024-09-27", reviewed=False, reason="dam is downstream of the gauge")
    assert narration.pick_lead([bad], helene=True) is None
    ok = item("dam", "2024-09-27", reviewed="title checked against the claim by hand")
    assert narration.pick_lead([ok], helene=True) is ok


def test_committed_context_gives_no_lead_for_newport_or_hepco():
    """After review: Newport's 1960 paper and Hepco's Walters Dam item are reviewed: false, and
    Newport's other two reports predate 2015, so neither site has a lead."""
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "data" / "context"
    for site in (NEWPORT, HEPCO):
        items = json.loads((root / f"{site}.json").read_text(encoding="utf-8"))["items"]
        assert narration.pick_lead(items, helene=True) is None, site


# --- Disagreement rule (b): change-visit note vs final cause, opposite signs ----------------


def test_rule_b_hepco_fallback_is_a_note_sign_disagreement(runs):
    r = runs[HEPCO]
    d = r["final"]["disagreement"]
    assert r["final"]["cause_status"] == "disagreement" and d["rule"] == "note_sign"
    assert d["best_guess"]["cause"] == r["final"]["cause"] == "fill"
    assert d["field_note"] == {"note": "Scour control changed", "date": "2024-12-17"}
    assert d["why_they_disagree"] == narration.note_vs_data("positive", "below the rating")
    assert d["recommended_check"]
    assert (
        "DriftWatch's agents rank fill first (40 %); the hydrographer's note says scour; the two "
        "disagree, so the cause is not settled."
    ) in r["narration"]


def test_rule_b_fires_even_when_the_skeptic_is_sure(runs):
    facts = runs[HEPCO]["facts"]
    top = Ranking(hypotheses=[Hypothesis(cause="fill", confidence=0.95, sign_matches=True)])
    d = fallbacks.disagreement(facts, top, confidence=0.95)  # rule (a) would not fire
    assert d is not None and d.rule == "note_sign"


def test_rule_b_newport_note_and_cause_agree(runs):
    assert runs[NEWPORT]["final"]["disagreement"] is None
    facts = runs[NEWPORT]["facts"]
    assert fallbacks.note_at_change(facts)["cause"] == "fill"
    top = Ranking(hypotheses=[Hypothesis(cause="fill", confidence=0.95, sign_matches=True)])
    assert fallbacks.disagreement(facts, top, confidence=0.95) is None


def test_rule_b_counts_only_control_changed_notes(runs):
    # Asheville: the change-visit note "Debris - Light" maps to debris (opposite sign to scour),
    # but it is not a 'control changed' note, so rule (b) does not fire and the cause stays open
    a = runs[ASHEVILLE]
    assert fallbacks.note_at_change(a["facts"]) is None
    assert a["final"]["cause_status"] == "open" and a["final"]["disagreement"] is None
    top = Ranking(hypotheses=[Hypothesis(cause="scour", confidence=0.95, sign_matches=True)])
    assert fallbacks.disagreement(a["facts"], top, confidence=0.95) is None
    # Hepco: "Scour control changed" at the change visit vs fill -> still rule (b)
    h = runs[HEPCO]
    assert fallbacks.note_at_change(h["facts"])["note"] == "Scour control changed"
    assert h["final"]["disagreement"]["rule"] == "note_sign"


def test_rule_b_synthetic_scour_note_and_scour_final_is_none(runs):
    facts = runs[HEPCO]["facts"]  # change-visit note: "Scour control changed"
    top = Ranking(hypotheses=[Hypothesis(cause="scour", confidence=0.9, sign_matches=True)])
    assert fallbacks.note_at_change(facts)["cause"] == "scour"
    assert fallbacks.disagreement(facts, top, confidence=0.9) is None
    # and rule (a) still fires below 0.6 when a control note names another cause
    other = Ranking(
        hypotheses=[Hypothesis(cause="datum_change", confidence=0.3, sign_matches=True)]
    )
    d = fallbacks.disagreement(facts, other, confidence=0.3)
    assert d is not None and d.rule == "low_confidence"
