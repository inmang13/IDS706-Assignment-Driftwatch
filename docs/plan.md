# DriftWatch — Triangle AI Hackathon plan (v2)

> v1 Fri 2026-11-06 8 pm · **v2 Fri 10 pm** after Grace's answers. Hacking ends Sun 8:30 am; DevPost 9:00; judging 10:00; finalist pitches 11:30.
> Grace works **8 am – 11 pm**. Real build time: ~1 h tonight, 15 h Saturday, 30 min Sunday, plus two unattended Orange Pi runs. Everything below is sized to that.
> Companion file: `docs/agent_playbook.md` — the how/where for Claude Code, Codex, Gemini, the Orange Pi, and the human.

## 0. One paragraph

**DriftWatch** is drift monitoring for the calibrated relationships water systems run on. ML teams have Evidently/Arize to tell them a model drifted; engineers have nothing equivalent for rating curves, meter calibrations, pump curves, or model calibrations. DriftWatch is a generic engine (get data → expected relationship → drift test → likely causes) plus a LangGraph investigator team that explains *why* in plain English and emits a glass-box **trust score**. This weekend: one module end-to-end — **river rating curves after Hurricane Helene** — on real USGS gauges, with a live view of the agents working; seven more modules specified in a registry.

## 1. Decisions (v2)

| ID | Decision | Why |
|---|---|---|
| H1 | **Name: DriftWatch**; RatingWatch = module #1. | "Drift" is the generic concept and the Enterprise-track vocabulary. |
| H2 | **Data: USGS rating curves, western-NC Helene gauges + Eno control.** | Verified Fri night (§3). Rain/radar and Durham meters go on the registry. |
| H3 | **Track: Finance, Enterprise & Tech**, framed as observability for physical infrastructure. Fallback: Social Impact. | — |
| H4 | **Drift test = Python-native Darienzo-style recursive segmentation** (baseline fit → weighted residuals → `ruptures` change-point → recurse → stable periods, shift times, shift size in ft and %). Cite Darienzo et al. 2021 / ShiftHappens as the method lineage; no R, no BaM in the stack. | Credible with hydrology judges, buildable in Python, and the output (stable periods + shift times) is exactly what the agents consume. |
| H5 | **Compute: Python `driftwatch` package + FastAPI on Cloud Run** (SSE stream of agent events, JSON reports, saved traces). **Product UI: Informer App** (gauge list, trust scores, run history, registry) once the tenant exists Saturday; the Informer front end opens the Cloud Run SSE stream directly for live narration, and an Informer server route stores finished traces. **Fallback UI: one static `console.html` served by FastAPI** — built *first* anyway as demo insurance and as the "engineer's console". | Grace picked live narration + registry as the demo moments; push/MCP are optional extras if time allows. Informer = live URL, auth, DB, hosting, prize eligibility. |
| H6 | **Agent runtime: Gemini via Vertex AI** (GCP credits). **Skeptic node: a different model family via OpenRouter.** Inkling/Tinker only if a key appears; no fine-tuning. | Keys in hand tonight: Gemini + OpenRouter. |
| H7 | Every LLM node has a deterministic fallback; every run saves a **replayable trace**. Snapshot data is the default; live USGS is a flag. | Demo insurance. |
| H8 | **Course reuse:** hackathon engine + eval suite feed IDS 706 Part 3 directly. Still a separate repo (`driftwatch`), cross-referenced in both READMEs. No instructor email. | Grace's call. |
| H9 | **Orange Pi runs two unattended jobs**: Fri night builds M1 from this spec; Sat night does docs/evals/registry. Both push a branch (`pi/m1`, `pi/docs`) and stop; Grace opens the PR from the link GitHub prints (the Pi's SSH key can push but cannot file a PR). Never push to main. Tests are the gate. | 8-to-11 working hours make the overnight compute the difference between a demo and a finished product. |
| H10 | **DevPost is submitted Saturday ~10:30 pm.** Sunday 8:00–8:30 is for edits only. Video recorded Saturday evening. | Hacking ends 8:30 am Sunday, 30 min into Grace's day. |

## 2. Pitch (unchanged from v1 except the method line)

- **Who:** utility/infrastructure managers first; then anyone building predictions or models on gauge data (forecasters, modelers, planners). UI copy is plain English, trust score first, "what should I do" second; the evidence panel carries the hydrographer detail (ft of shift, control condition).
- **Numbers to say out loud:** every US streamflow number is computed from stage through a rating curve. Helene set 18 provisional flood records in NC and left 40+ gauges needing indirect measurements. Our check: Pigeon River at Canton post-Helene measurements sit 20–38 % below the pre-storm rating; French Broad at Newport TN 33–51 % below. A USGS study of 174 Virginia gauges found the median lag between a shift starting and being entered was ~240–300 days through 2001 and still months after (SIR 2017-5137).
- **Differentiation table** (keep in slides):

| What exists | Does | Gap |
|---|---|---|
| Aquarius Time-Series (Xylem), WISKI (Kisters) | Operational hydrometric databases: rating editing, shift management, alerts | Expert-driven, vendor silo, no "why", no generalization |
| BaRatin / BaM! / **ShiftHappens** (INRAE; Darienzo 2021, Mansanarez 2019) | Bayesian rating curves + recursive change-point segmentation of gaugings — the research state of the art | R/Fortran, one relationship type, no explanation layer. **We implement their segmentation idea in Python and put agents around it.** |
| USGS shift-adjusted ratings, IV_SYNC | Hydrographers apply shifts after each measurement | Manual, per gauge |
| Evidently / Arize / NannyML / WhyLabs | Drift monitoring for ML models | The pattern we want — for software, not for physical calibrations |
| Trinnex waterCAST, Innovyze Info360, Xylem Vue | Utility analytics platforms ("glass-box AI") | Platforms, not a drift primitive — DriftWatch is the module they'd plug in |

- **One-liner:** *Rating-curve tools find the shift if an expert is looking. ML-ops tools watch models, not meters. DriftWatch watches any engineered relationship, explains the drift in plain English, and gives a trust score anyone can act on.*
- **3-minute pitch:** hook (gauge wrong by a third) → generalize (every utility runs on unwatched calibrations) → live demo Canton then Swannanoa → engine + registry → eval table → next step (meter under-registration with a utility partner).

## 3. Data (verified Fri night; details in v1 archived below)

Sites: **03459500 Pigeon R at Canton** (hero, −32 %, "Scour control changed"), **03455000 French Broad at Newport TN** (hero #2, −43 %, "Fill control changed"), 03446000 Mills R (−11 %, Watch), 03451500 French Broad at Asheville (check), **03451000 Swannanoa at Biltmore** (control), **03463300 North Toe at Altapass** (control), 03479000 Watauga (control), **02085000 Eno at Hillsborough** (Durham-local control).

Rules carried over from the course reviewer: pair each discharge with the `reading_type='MeanGageHeight'` stage row on (`field_visit_id`,`time`); never use channel area/velocity as predictors (Q=A·V leakage) — evidence only; report stage shift in **ft** for the evidence panel and **%** flow error for the trust score; keep `b`,`e` fixed from the base rating and let `a` slide; exclude Sept 27 2024 flood-peak measurements (Poor, indirect) from the test, plot them as context; `time` is UTC.

Sign convention (encode + explain in UI): scour → residual positive; fill/aggradation → negative; debris/vegetation → negative, usually transient; datum change or gauge rebuild → a step of either sign with no channel evidence. **Canton's note (scour) disagrees with its sign (negative): either a rebuild/datum story or an artifact of my quick fit — re-check with proper pairing before pitching it; Newport is the safe hero.**

## 4. Architecture

```
driftwatch/
  core/        DriftModule protocol · TrustScore · Report/Trace pydantic schemas
  modules/rating_curve/   usgs.py (fetch+snapshot) · pairing.py · rating.py · segmentation.py · causes.py
  modules/specs/*.yaml    7 specified modules (four slots each) → registry
  agents/      graph.py · tools.py · prompts/ · fallbacks.py · trace.py
  api/         FastAPI: GET /gauges · GET /report/{site} · POST /run/{site} (SSE) · GET /trace/{id} · GET /replay/{id} (SSE, 0.6 s pace) · GET /registry · console at / · static console.html
data/snapshot/  committed JSON per site
evals/          cases.yaml · run_evals.py
informer-app/   (Sat) front end + server/ + migrations/ + informer.yaml
docs/           plan.md · agent_playbook.md · decision_log.md · pitch.md · devpost.md
```

**DriftModule** = `fetch(target, source) → Dataset`, `expected(ds, reference) → Relationship`, `drift_test(ds, rel) → DriftResult`, `causes: list[Cause]`.

**drift_test (H4):** fit baseline on the reference window (weighted log-space power law, weights from `measurement_rated`); residuals r_k = (Q_k − Q̂(H_k))/Q̂(H_k) and the equivalent stage shift Δh_k = Ĥ(Q_k) − H_k (USGS gage-height shift convention, same sign as r_k: scour → positive in both % and ft); change-point search on r (ruptures PELT, cost = l2, penalty tuned so Eno stays quiet); recurse into segments ≥ 6 points; output `stable_periods[]`, `shifts[] {time, size_pct, size_ft, direction, n_after, confidence}`.

**TrustScore** (glass-box, print the arithmetic): 100 − |recent median residual| term (0–50; was 0–40 until 2026-11-07) − staleness since last measurement (0–20) − measurement quality (0–15) − unresolved field-note flags (0–15) − insufficient data (0–10). Bands: Trusted ≥ 80 · Watch 50–79 · Stale < 50.

**Agents (LangGraph):** `triage` (no LLM) → `evidence_collector` (tools: channel geometry trend, field notes, flood context between last good and first drifted visit, site metadata, ≤1 web search) → `hypothesis_ranker` (Gemini, structured JSON, always includes *datum/rebuild* and *inconclusive*) → `skeptic` (OpenRouter, different family; checks sign vs cause, evidence sufficiency; accept or typed objection, ≤2 loops) → `narrator` (120 words for a utility manager + what to do next + score card). Each node emits `{node, status, payload}` → SSE; trace saved.

**UI:** `console.html` (Plotly: stage–discharge scatter with base curve, residual timeline with Helene marked and shift times; 5-box agent graph that glows; streaming log; finding card; registry tab from the YAML). Informer app reproduces the gauge list, finding cards, run history, and registry with the platform's auth/DB/hosting, and embeds or links the live console for the run.

## 5. Model plan — summary (the playbook has the prompts)

| Resource | Role |
|---|---|
| Claude Code (Opus for architecture, Sonnet for routine) | Primary builder, max 2 worktrees (`backend`, `ui`). |
| Orange Pi (thoth: 4-core aarch64, 4 GB RAM shared with other services, Python 3.13) + Claude Code | Fri night: build M1 from §4 + playbook prompt, push branch. Sat night: docs, evals, registry YAML, DevPost text, push branch. Runs with `LLM=fallback` (no Gemini/OpenRouter keys on the box). |
| Gemini on Vertex | Agent runtime (ranker, narrator, tool-calling collector). |
| OpenRouter | Skeptic (different model family) and fallback runtime. |
| Codex (free) | Independent reviewer at M1, M2, M3; writes `evals/` if Pi hasn't. |
| Gemini in VS Code | Inline edits, docstrings, commit messages. |
| Claude chat (this) | Pitch coaching, DevPost copy, prompt review, decisions. |

## 6. Eval suite
`evals/cases.yaml`: Canton → Stale, cause ∈ {fill, datum/rebuild}, skeptic raises sign/notes mismatch · Newport → Stale, fill, cites "Fill control changed" · Mills → Watch · Swannanoa, North Toe, Eno → Trusted, no invented cause · synthetic +25 % step injected into Eno at 2025-07-01 → fires, scour on top · replay determinism. Report pass/fail + tokens + wall time. Doubles as IDS 706 Part 3 evidence.

## 7. Schedule (ET) — sized to 8 am–11 pm

| When | h | Build | Milestone |
|---|---|---|---|
| **Fri 10–11 pm** | 1 | Create repo (`driftwatch`, public), drop in `CLAUDE.md` + this plan + playbook; Claude Code: scaffold + `usgs.py` fetch + commit `data/snapshot/` for the 8 sites; Orange Pi prep (~10 min: clone, venv, `make install`; Claude Code and the push key are already on the box); launch Pi job #1 at ~11 pm. | **M0:** snapshot committed, Pi running. |
| Fri night (Pi) | — | Job #1: pairing, rating fit, segmentation, trust score, CLI, tests, `report.json` for 8 sites. Pushes `pi/m1` (no PR; Grace opens it). | — |
| **Sat 8–9:30** | 1.5 | Review Pi PR: run tests, check Canton/Newport fire and controls stay quiet, fix with Claude Code. Codex review #1. | **M1** |
| **Sat 9:30–1:00** | 3.5 | Agents: graph, tools, prompts, fallbacks, trace. Gemini + OpenRouter wired. Run all 8 sites. (If the Informer tenant lands during this block, do the 30-min spike at the next natural break.) | **M2:** 8 traces, Canton/Newport fire, controls quiet. |
| **Sat 1:00–3:30** | 2.5 | FastAPI SSE + `console.html` (scatter, residual timeline, glowing graph, log, finding card). | **M3:** full live demo locally. |
| **Sat 3:30–4:00** | 0.5 | Informer spike: CLI login, plugin, hello app with a server route fetching Cloud Run. Go/no-go. | — |
| **Sat 4:00–6:30** | 2.5 | Go: Informer app — gauge list + finding cards + run history + registry tab, live console embedded/linked; `inf deploy`. No-go: polish console, add registry tab there. | **M4:** product UI at a real URL. |
| **Sat 6:30–8:00** | 1.5 | Cloud Run deploy of the Python service; CORS for Informer; evals run; Codex review #3. | **M5:** public demo end to end. |
| **Sat 8:00–9:00** | 1 | **Code freeze on core/agents.** README, DevPost text, 6 slides (title, problem+numbers, demo, engine+registry, evals, next). | — |
| **Sat 9:00–10:30** | 1.5 | Record 2-min video (screen + voice, one take), screenshots, **submit DevPost**. Launch Pi job #2. | **M6: submitted.** |
| Sat night (Pi) | — | Job #2: README polish, registry YAML completeness, eval report, pitch script draft. Push `pi/docs` only. | — |
| **Sun 8:00–8:30** | 0.5 | Merge job #2 if green; edit DevPost; final push before 8:30. | — |
| Sun 10:00 / 11:30 | — | Judging from snapshot mode; finalist pitch. | — |

**Cut order (bottom first):** Informer app → registry tab → Cloud Run (demo locally) → web-search tool → Asheville gauge → skeptic loop (keep a single-pass skeptic). **Never cut:** M1, M2, replayable trace, video, DevPost by Saturday night.

## 8. Risks
| Risk | Mitigation |
|---|---|
| Pi job #1 produces something wrong overnight | Spec is tight (§4 + playbook); tests + fixture gauges gate it; worst case Claude Code rebuilds M1 in 2 h Saturday morning — still inside the schedule. |
| Informer tenant arrives late or sandbox can't reach Cloud Run | Console page exists by 3:30 pm regardless; Informer is additive. |
| Gemini/OpenRouter outage in judging | Replay traces; deterministic fallbacks. |
| Canton puzzle is an artifact | Newport is the hero; Canton becomes a second example. |
| Hydrology judge | Lead with the Virginia lag stat; name Darienzo/ShiftHappens as the lineage; never say USGS flows are wrong — say latency and everything that isn't a gauge. |
| Rate limits on Claude Code during the Pi job | Job runs at low intensity (one task at a time, tests between); if quota hits, it stops cleanly with the branch pushed. |

## 9. DevPost checklist
Name · tagline ("Drift monitoring for the relationships water systems run on") · public repo · live URL (Informer and/or Cloud Run) · video · built-with (Python, LangGraph, Gemini/Vertex AI, OpenRouter, Google Cloud Run, FastAPI, Plotly, Informer Apps, USGS Water Data API) · track Finance/Enterprise/Tech · 3 screenshots · "What's next" · note on the IDS 706 relationship.

---

## Archive — v1 data table (Fri night check)
| Gauge | Post-Helene n | Median residual | Field note |
|---|---|---|---|
| 03459500 Pigeon R at Canton | 18 | −32 % | Scour control changed (Dec 2024) |
| 03455000 French Broad at Newport TN | 17 | −43 % | Fill control changed (Oct 2024) |
| 03446000 Mills R nr Mills River | 17 | −11 % | Debris – Moderate |
| 03451500 French Broad at Asheville | 16 | +32 % (first visits ≈ 0) | — |
| 03451000 Swannanoa R at Biltmore | 12 | +9 % | Clear |
| 03463300 N Toe R at Altapass | 11 | +1 % | Debris – Light |
| 03479000 Watauga R nr Sugar Grove | 13 | +4 % | Vegetation – Heavy |
Method: power-law fit on 2012 → Sept 2024, residual = (Q_meas − Q_curve)/Q_curve. Endpoint: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/field-measurements/items?f=json&monitoring_location_id=USGS-<site>`.
