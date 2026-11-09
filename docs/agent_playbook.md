# DriftWatch — agent playbook (v3)

> How and where each agent is used, with paste-ready prompts, and what the human does at the same time. Pair with `docs/plan.md`.
> v1 Fri 10 pm · v2 Fri 11 pm (thoth edits) · v3 Sat 10:30 am · v3.1 Sat 12:45 · **v3.2 Sat 1:20: M2 done, C8 thoth job added, Boot Camp reference in C5, reference-mode answer in F.** Grace works 8 am – 11 pm.

## A. Rules for every agent session

1. **Start every session with:** "Read `CLAUDE.md`, `docs/plan.md` §4, `docs/decision_log.md`, and the section of `docs/agent_playbook.md` for this stage. Summarize in 5 lines what you will build and what 'done' means, then wait for my OK." (Unattended thoth jobs skip the wait.)
2. **Plan before code** for anything over ~100 lines: file list and function signatures first.
3. **One stage per session, one branch per stage.** Finish → `make test` + `make demo` → commit → push → PR. Start a fresh session for the next stage.
4. **Tests are the gate.** If a session can't get `make test` and `make demo` green, roll back to the last green commit instead of patching forward.
5. **Snapshot is the default source.** Only `usgs.py` calls the live API, and only with `SOURCE=live`.
6. **Tests never call an LLM** (`LLM=fallback`).
7. **Commit messages:** `<stage>: what`, at every green step.
8. **Agents edit `docs/plan.md` only when the prompt says so.** Otherwise they append a dated line to `docs/decision_log.md`.
9. **Hard stop times are real.** At the stop time an agent pushes what's green and writes `docs/<stage>_status.md`.
10. **Two machines never edit the same files at once.** Laptop sessions own `driftwatch/core`, `driftwatch/agents`, `driftwatch/api`, `driftwatch/modules/rating_curve`. Thoth's daytime job owns `driftwatch/modules/specs/` and `driftwatch/modules/registry.py` only.

## B. Status board (Sat 10:30 am)

| Stage | State | Where |
|---|---|---|
| M0 scaffold + 8-site snapshot | ✅ merged | main |
| M1 engine: pairing, rating fit, shift detection, causes, trust score, CLI, 8 reports | ✅ merged (overnight on thoth) | main |
| M1 fixes: cap 50, exact pairing, UTC, below-zero-flow guard, dashes, n_after, Helene visits counted for staleness, null test, docs | ✅ reviewed, **merge now** | PR `m1-fixes` |
| M2 agents | ✅ done 1:05 (90 tests; Disagreement schema; structured narrator; Hepco run 4 = replay default) | PR `m2-agents` — **merge now** |
| Registry specs (thoth) | ✅ merged (11:50) | main |
| Informer spike | ✅ GO at 12:13 | `C:\Users\Grace\informer-spike\` |
| Thoth afternoon job: Δh test, quality weighting, suggested shift, auto reference | ▶ 2:00 – 4:00 (C8) | `pi/dh-test` |
| M3 console · M4 Informer · M5 deploy + evals · DevPost | later today | — |

**Current results (after fixes):** Pigeon R near Hepco Stale 24 (−28 % since Dec 2024) · French Broad at Newport Stale 30 (−43 % since Oct 2024, "Fill control changed") · French Broad at Asheville Stale 46 (+36 % since Jul 2025, delayed) · Mills Watch 73 · Swannanoa 94, South Toe 95, Watauga 95, Eno 91 Trusted.

**Demo roles:** Newport = main demo, run live (fill 0.75, ~30 s). Hepco = the skeptic demo, **replay of run 4** (objection → revised → Disagreement → "uncertain, here is what to check"). Narrate Hepco as *the system refused to overrule the hydrographer without proof*, not as *the evidence proved a cause* — the ranker's final pick (datum change) is not what the channel numbers favour, and the Disagreement says so. Asheville = "the storm passed, the gauge looked fine for 10 months, then it wasn't." Swannanoa = record flood, rating held, engine stays quiet.

**Not in the pitch yet:** any channel area/speed percentages. They come from the M2 evidence tool or not at all.

## C. Saturday from here

| When | Machine | Human |
|---|---|---|
| **10:30 – 10:45** | — | Merge `m1-fixes`. Put Gemini credentials path + OpenRouter key in the **laptop** `.env` (never on thoth). Start thoth's registry job (C2). |
| **10:45 – 2:00** | **Claude Code (laptop): M2 agents** (C1). **Thoth: registry specs** (C2). | Draft `docs/pitch.md`. From ~12:00 read the first Gemini narrations; edit tone in `driftwatch/agents/prompts/`. Eat lunch while tests run. |
| **~1:15** | **Codex review #2** (C1, end). | Paste Codex's list into the M2 session; it fixes before the 2:00 stop. |
| **2:00 – 4:30** | **Claude Code (laptop): M3 console** (C3). **Thoth: C8** (Δh test, weighting, suggested shift, auto reference) on `pi/dh-test`. | Watch the first live run on the page; write down every moment a judge would be confused → prompt edits. |
| **after M3 merge – 6:30** | **Claude Code + Informer plugin: M4 product UI** (C5). Informer spike passed 12:13 (C4). | Test on your phone as it deploys; confirm viewers need no sign-in. |
| **6:30 – 8:00** | **Claude Code: M5 Cloud Run deploy + evals** (C6). **Codex review #3** at ~7:30. | Open the live URL on your phone; fix order = what Codex and you both hit. |
| **8:00** | **Freeze `core/`, `agents/`, `modules/rating_curve/`.** | — |
| **8:00 – 9:15** | Claude chat: README, DevPost text, 6 slides from `docs/pitch.md`. | Approve every claim in the text against `docs/m2_results.md` and `docs/eval_report.md`. |
| **9:15 – 10:30** | — | Record the 2-minute video (C7). Screenshots. **Submit DevPost by 10:30.** |
| **10:30 – 11:00** | Launch thoth job #2 (D). | Stop at 11. |

**Cut order if behind (cut from the top):** web-search tool (already out) → Informer push/MCP extras → Informer run-history page (keep gauges + detail + registry) → Cloud Run (demo from the laptop) → Asheville in the video → skeptic loop (keep one skeptic pass). **Never cut:** M2 with fallback, replayable traces, the console, the video, DevPost submitted Saturday night.

### C1 · M2 agents — Claude Code, laptop, branch `m2-agents`, stop 2:00 pm
Paste:
> Read CLAUDE.md, docs/plan.md §4 "Agents", docs/agent_playbook.md A, docs/m1_results.md, docs/decision_log.md. Branch `m2-agents`. Build `driftwatch/agents/`: LangGraph StateGraph triage → evidence_collector → hypothesis_ranker → skeptic → narrator, edges as plan §4 (a skeptic objection loops back to the ranker at most twice; a Trusted gauge goes triage → narrator). Triage reads the M1 Report; no LLM.
> Tools (`tools.py`, pure Python, no LLM): `channel_geometry_trend(site, shift_time)` loads `channel-measurements` straight from the snapshot (the Dataset doesn't carry them), joins to paired stage on field_visit_id, fits ln(area) and ln(velocity) against ln(H − e) separately before and after the shift, and reports the % difference at the median post-shift stage, plus median width before/after and n of each. `field_notes(site, since)`; `flood_context(site)` (largest measured discharge between the last pre-shift and first post-shift visit, including Helene-excluded ones); `site_metadata(site)`. No web search.
> LLM (`llm.py`): `gemini` (langchain-google-vertexai), `openrouter` (langchain-openai, base_url https://openrouter.ai/api/v1; skeptic only), `fallback` (rules: the ranker picks the catalog cause whose sign matches and has the most evidence; the skeptic objects when the top cause's expected sign contradicts the residual or the channel evidence, else accepts; the narrator fills a template). Structured outputs via pydantic. The ranker always lists datum_change and inconclusive with a confidence. The skeptic must use channel_geometry_trend: if speed fell much more than area changed, argue for fill/backwater on the downstream control over datum change. The narrator writes ≤ 120 words for a utility manager: what's wrong, how sure we are, what to do next, the score. Prompts live in `driftwatch/agents/prompts/*.md` so Grace can edit tone without touching code.
> Every node emits a TraceEvent {node, status, payload, t} to an asyncio queue and to traces/<site>-<ts>.json; `replay(trace_path)` yields the same events. `make run SITE=…` prints the narration and writes the trace; `make demo` adds `make run` for 03459500 and 03451000 with LLM=fallback.
> Tests (LLM=fallback, offline): graph compiles; Hepco ends with ≥ 1 skeptic objection and a final cause other than plain scour; Newport → fill; Asheville → a positive-sign cause; Swannanoa → no cause; replay determinism.
> Then run all 8 with LLM=gemini and write docs/m2_results.md: per gauge the final cause and confidence, whether the skeptic objected and why, the channel_geometry_trend numbers for Hepco, Newport and Asheville, tokens and wall time per run. Commit at each green step; push; open a PR. Hard stop 2:00 pm: push what's green and write docs/m2_status.md.

**Codex review #2 (~1:15), paste into Codex:**
> Review branch m2-agents. Rank: (1) any LLM output that can crash the graph or loop forever; (2) places where the fallback path and the LLM path disagree on structure; (3) evidence numbers in docs/m2_results.md that the code does not reproduce; (4) anything in a narration that claims more certainty than the evidence. Checklist only, no rewrites.

### C2 · Thoth daytime job — registry specs, branch `pi/registry`, unattended
Save as `docs/prompts/pi_registry.md` on main, then on thoth: `git pull && git checkout -B pi/registry origin/main && nohup claude -p --permission-mode acceptEdits --max-turns 120 "$(cat docs/prompts/pi_registry.md)" > logs/pi_registry.log 2>&1 &`
> You are working unattended on thoth. Read CLAUDE.md and docs/plan.md §4 "The generic engine". You may only create or edit files under `driftwatch/modules/specs/`, `driftwatch/modules/registry.py`, `tests/test_registry.py`, and append to `docs/decision_log.md`. Do not touch anything else; another agent is editing the rest of the repo right now.
> 1. Write 8 YAML specs in `driftwatch/modules/specs/`, one per module: `rating_curve` (status: live), and status: specified for `sewer_meter_mass_balance`, `meter_under_registration`, `pump_curve`, `reservoir_stage_storage`, `well_specific_capacity`, `model_calibration`, `rain_gauge_vs_radar`. Each has: `name`, `title` (plain English), `status`, `who_cares` (one line, a utility role), `why_it_drifts` (one line), and the four slots `get_data`, `expected_relationship`, `drift_test`, `likely_causes` (2 sentences each, concrete: name the real data source, e.g. SCADA pump run-times, AMI meter reads, NEXRAD/MRMS radar, USGS field measurements). For `rating_curve`, describe what is actually built (USGS OGC field measurements; weighted power-law rating; recursive change-point segmentation of residuals; scour/fill/debris/vegetation/datum change). No marketing language.
> 2. `registry.py`: `load_registry() -> list[ModuleSpec]` (pydantic model), validates every file, sorted live first. `tests/test_registry.py`: all 8 load, exactly one is live, every slot is non-empty.
> 3. `make test` green. Commit `registry: <what>` after each step; `git push -u origin pi/registry`; write `docs/registry_status.md`. Stop.

### C3 · M3 console — Claude Code, laptop, branch `m3-console`, stop 4:30 pm
Merge `m2-agents` and `pi/registry` into main first. Paste:
> Read CLAUDE.md, plan §4 "UI", docs/m2_results.md. Branch `m3-console`. Build `driftwatch/api/app.py` (FastAPI): GET /gauges (site, name, band, score), GET /report/{site}, POST /run/{site} streaming TraceEvents as SSE (LLM from env), GET /trace/{id}, GET /replay/{id} (SSE at human pace, ~0.6 s between events), GET /registry (from `driftwatch.modules.registry.load_registry()`), static `console.html` at `/`. CORS configurable via `CORS_ORIGINS`.
> The page (one file, vanilla JS + Plotly from a CDN, works on a phone): left, gauge list with band colours, Newport first; center, stage–discharge scatter (reference-window points vs post-shift points in two colours, base curve drawn, Helene-excluded points hollow) above a residual timeline with Helene (2024-09-27) and detected shift dates as vertical lines; right, a 5-box agent graph that highlights the running node, plus a streaming log showing each node's key output in one line; bottom, the finding card: narration, cause + confidence, and the score arithmetic (every deduction with its reason). A "Replay" button uses /replay on the latest saved trace so the demo works with no LLM. Registry tab: 8 cards from /registry, live first, each showing the four slots.
> Replay reads `traces/replay_defaults.json` first, then the newest trace. A Disagreement renders on the finding card as four labelled rows: best guess · field note · why they disagree · double-check. Asheville's card says the cause is open. Each replayed run shows a "replay of <time>" label. `make serve`. Then run Newport live and replay Hepco (run 4) and Swannanoa; take screenshots into docs/images/. Also re-run Mills once with LLM=gemini so its trace uses the structured narrator. Commit, push, PR. Stop 4:30 pm.

### C4 · Informer spike — DONE 12:13, result GO
A minimal app is live on `inman.go.informer.cloud`; its server route reaches the USGS API and renders a station name. Deploy works; routes can reach an outside API. Spike code moved to `C:\Users\Grace\informer-spike\` (never commit it onto a code branch).

Findings that shape C5:
1. **Outside APIs must be declared.** Server-route `fetch` reaches only Informer paths. Declare each outside API as an app-owned integration in `informer.yaml` (`authType: none`, `apiBaseUri: <url>`) and call it with `context.<slot>.request({ method, url })`. Pattern: the App Builder Boot Camp app already on the tenant.
2. **Cloud Run goes through the same integration**, server-side. `CORS_ORIGINS` on the Python service only matters if the page itself fetches from the browser.
3. **Embedding the console or its SSE stream in an Informer page needs admin approval** (Informer Admin → Approved Resources, Asset type `data`). The "Run investigation" button opens the console in a new tab and avoids this.
4. Login is a browser sign-in (`inf login <url>`, `--no-browser` prints the link). CLI needs Node 22+.
5. **Windows:** `inf deploy` crashes in its own build step. Rename the app's build script to `build:web`, run `npm run build:web` before every `inf deploy`, or `npm run deploy` which does both.

Not yet verified: phone layout; whether viewers need a sign-in; whether the integration reaches your own API (only USGS was tested). C5 checks all three in its first 20 minutes.

### C5 · M4 Informer product UI — can start as soon as M3 is merged (was 5:00)
Folder `informer-app/` at the repo root on branch `m4-informer`, Informer plugin loaded. Paste:
> Read docs/agent_playbook.md C4 findings first. The App Builder Boot Camp app on this tenant is the reference: follow its stations "Give Desk a database" (migrations), "Show the queue" (list page from a server route), "Open a way in" (inbound route), "See changes live" (live updates), "Let anyone report a problem" (public access without sign-in). Build an Informer App called DriftWatch for a utility manager. Declare an app-owned integration in `informer.yaml` for `<cloud-run-url>` (`authType: none`) and make every server-side call to it through that slot's `request()`; never use bare fetch for outside URLs. First 20 minutes: a page that lists `/gauges` through the integration, deployed, opened on a phone, and confirmed whether a viewer needs to sign in; report before building more. Then pages: (1) Gauges: cards with name, trust band colour, score, one-line finding; (2) Gauge detail: finding card with the score arithmetic, the evidence, and for a Disagreement the four fields (best guess, field note, why they disagree, double-check); a "Run investigation" button that opens `<console-url>/?site=<site>` in a new tab; a server route that fetches `/trace/<id>` through the integration after a run and stores it; (3) Run history from Postgres (migration: runs(site, started_at, band, score, cause, trace_json)); (4) Registry from `/registry`. Phone-first, fast. Windows: build script named `build:web`; deploy with `npm run deploy`. Print the URL.
> Optional only if done 90 minutes early: a scheduled agent that re-runs all gauges nightly and a push notification when a band changes.

### C8 · Thoth afternoon job — Δh test, weighting, suggested shift, auto reference · branch `pi/dh-test` · 2:00 – 4:00
Save as `docs/prompts/pi_dh.md` on main first. On thoth: `git pull && git checkout -B pi/dh-test origin/main && nohup claude -p --permission-mode acceptEdits --max-turns 150 "$(cat docs/prompts/pi_dh.md)" > logs/pi_dh.log 2>&1 &`
> You are working unattended on thoth. Read CLAUDE.md, docs/plan.md §4, docs/decision_log.md, and docs/usgs_rating_review.md if present. You may edit only `driftwatch/modules/rating_curve/segmentation.py`, `report.py`, `pairing.py` (reference window only), `driftwatch/core/schemas.py` (additive fields only), their tests, and append to docs/decision_log.md. Another agent owns `driftwatch/api/` and `driftwatch/agents/` right now; do not touch them.
> 1. Two residual series. Run the change-point search on both the percent-of-flow residual (current) and the stage-shift residual in ft. Report both shift lists and, per gauge, which series shows the larger standardized step, plus `low_flow_concentrated: bool` (post-shift residuals larger in the lowest third of flows than in the top third). USGS treats scour and fill as changes to the zero-flow height, so a step that shows mainly in ft at low flows is a clue for the agents.
> 2. Quality weighting. Exclude Poor-rated measurements from the change-point search (keep them in plots and counts); compute every shift size as a quality-weighted median.
> 3. Suggested shift. Add `suggested_shift_ft` and `suggested_shift_n` to the Report: the weighted median stage shift over the latest stable period, labelled provisional ("a hydrographer confirms").
> 4. Reference mode. Add `reference_mode: fixed | auto`. `fixed` = today's windows. `auto` = the most recent stable period with at least 15 measurements spanning at least 2 years, re-derived from the segmentation on the full history; the Report records the mode and the window used. Default stays `fixed`. Run all 8 gauges in both modes and tabulate where the band or top shift differs.
> 5. Tests for 1–4. `make test` green, `make demo` green. Write docs/dh_results.md (tables for 1 and 4, plus any surprise). Commit per step, push `pi/dh-test`, write docs/dh_status.md. Stop by 4:00.

### C6 · M5 deploy + evals — Claude Code, laptop, branch `m5-deploy`, stop 8:00 pm
> Read CLAUDE.md and plan §6. (1) Dockerfile (python:3.13-slim, snapshot and saved traces baked in, `uvicorn driftwatch.api.app:app --port 8080`). `gcloud run deploy driftwatch --source . --region us-east1 --allow-unauthenticated`, Gemini via the service account, OPENROUTER_API_KEY from Secret Manager, CORS_ORIGINS set to the Informer app origin. Print the URL and smoke-test /gauges and /replay. (2) `evals/cases.yaml` + `evals/run_evals.py` + `make evals` → `docs/eval_report.md`: Newport → Stale, fill, cites "Fill control changed"; Hepco → Stale, skeptic objects at least once, output is a Disagreement whose field_note is the scour note and whose best_guess is not scour; Asheville → Stale, positive-sign cause; Mills → Watch; Swannanoa, South Toe, Watauga, Eno → Trusted with no cause named; synthetic +25 % step injected into Eno at 2025-07-01 → fires; synthetic no-step Eno series → 0 shifts; replay determinism. Report pass/fail, tokens, wall time per case, with LLM=fallback and LLM=gemini columns. Commit, push, PR.

**Codex review #3 (~7:30):** *"You are a judge opening `<live-url>` on a phone for 90 seconds. What breaks, what's slow, what's confusing? Top 5, ranked."*

### C7 · Video (9:15 – 10:30), 2 minutes, one take
20 s problem (every flow number is computed; Helene) → 50 s Newport live run (agents light up, finding card) → 25 s Hepco: the skeptic objects to "scour" → 15 s Swannanoa: record flood, rating held, quiet → 10 s registry + eval table. Use Replay if the live call is slow.

## D. Thoth job #2 — Sat night, unattended (docs only), branch `pi/docs`
> Read CLAUDE.md and docs/plan.md. Do not modify anything under driftwatch/. Tasks: (1) README: clean-clone instructions verified by actually running them in a fresh venv on this machine. The install step must be `pip install -e ".[dev,agents,api]"` (what `make install` runs), not `pip install -e ".[dev]"`: without the `agents` and `api` extras, tests/test_agents.py and tests/test_api.py fail to import (no langgraph / fastapi). Say so in the README, and list httpx if the fresh venv shows it is needed (it is already a core dependency in pyproject.toml); architecture diagram as Mermaid; the differentiation table from plan §2; links to the live URL and the DevPost page from docs/devpost.md; the IDS 706 relationship note. (2) Run `make evals` with LLM=fallback and refresh docs/eval_report.md's fallback column only. (3) `docs/pitch_script.md`: a 3-minute script with timings from docs/pitch.md for the 11:30 finalist round. Commit after each task; push `pi/docs`; write docs/pi_docs_status.md; stop.

## E. Sunday 8:00 – 8:30
Merge `pi/docs` if `make test` is green; otherwise merge only README and pitch_script. Final DevPost edits (live URL, video, screenshots). Done by 8:30. Judging runs on the live URL with Replay as the fallback; keep `make serve` running on the laptop as a backup.

## F. Human-only jobs
- Confirm the demo roles in B (Newport main, Hepco skeptic, Asheville delayed, Swannanoa quiet).
- Approve every narration's tone and every number in the pitch before it goes in the video.
- Judge question to have ready: *"How does it know the reference curve going forward?"* Answer: for the demo the reference is pinned to pre-Helene so the result can be checked against a known event; in operation it is the latest stable period, re-derived every run (`reference_mode: auto`, C8), which is how a hydrographer thinks about the current rating. Drift against USGS's own published rating is the next step (ideas doc).
- Keep `docs/decision_log.md` honest: every cut gets a dated line.
- Eat lunch and dinner; stop at 11.

---

## Archive — Friday (done)
- M0 prompt and thoth setup: see git history of this file (v2) and `docs/prompts/pi_job1.md` + `scripts/pi_job.sh`.
- The repo `CLAUDE.md` is now the canonical copy (Hepco / South Toe names, Python 3.11+); the block that used to live in section B of this playbook is retired.
