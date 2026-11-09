# Overnight review of main (feeaf98), 2026-11-08 00:10–00:40 EST, thoth

**Verdict: nothing a judge can type crashes the server, and every engine number reproduces.**
Bad input gets a clean 404, 400 or 422 everywhere. All 8 `reports/*.json` rebuild byte-for-byte
(apart from `generated_at`). The README clean-clone steps all work. The real risks are softer:
a live Run freezes the server for everyone for a few seconds, a live Run quietly replaces a
gauge's Replay, a cold start takes about 20 s, and at Asheville (cause open) three pieces of
on-screen text still name scour as if it were settled.

Method: read the code; probed a scratch server (copied trace dir, `LLM=fallback`, port 8011)
with good and bad requests; ran `make report` for all 8 into a temp dir and diffed; ran fresh
fallback runs on Hepco, Newport and Asheville and diffed them against the Replay-default Gemini
traces; ran the clean-clone steps in a fresh clone and venv; ran `make evals` in that clone.
Second opinions came from Clay's NIP models (nip-medium and nip-large). I checked every point
they raised against the code before using it. Two of them made it into finding 4; the rest were
generic or wrong (for example, "`finding()` returns an undefined `out`", which was an artefact of
the excerpt I sent).

## Top 10, ranked

1. **POST /run freezes the whole server while it runs** (crash class 1, a hang rather than a 500).
   `driftwatch/agents/graph.py:333-353`: the `triage` and `evidence_collector` nodes are
   `async def` but call the synchronous report and tool code directly, on the event loop. Measured:
   a `/registry` call made during a fallback Newport run took **4.74 s**, against 0.08 s before
   and after. On a cold instance, or with several judges, every page and Replay stream stalls for
   the length of the sync part of each run. The Gemini calls themselves are awaited and don't block.

2. **A live Run replaces that gauge's Replay** (wrong data). `driftwatch/agents/trace.py:96`
   (`latest_trace`) falls back to the newest `traces/<site>-*.json` for any site that is not in
   `replay_defaults.json`, and POST /run writes into `traces/`
   (`driftwatch/api/app.py:374`). Verified: after one POST /run on South Toe, `/gauges` reported
   its Replay as the new `03463300-20261108T053133785148Z` (llm `fallback`) in place of the
   committed trace. This affects 5 gauges (Mills, Swannanoa, South Toe, Watauga, Eno). The 3 pinned
   gauges are safe. On Cloud Run the effect lasts until the instance restarts.

3. **First request takes about 20 s** (looks like a hang). `driftwatch/api/app.py:276-291`:
   `/gauges` builds all 8 reports in series on first call, and there is no warm-up at startup.
   Measured 20.8 s on thoth, and **16.1 s on Cloud Run at 00:35**. The console calls `/gauges`
   first, so a judge sees a blank page for that long.

4. **Asheville (cause open): on-screen text names scour as if settled** (item 3).
   - Card, "Skeptic" row (`driftwatch/api/console.html:834`) prints the Skeptic's argument
     verbatim: "…which matches scour, and the channel trend supports a real control change…". The
     narration guard keeps mechanism words out of the narration, but this row bypasses it.
     (Flagged by nip-large; checked.)
   - Hero picture (`console.html:1035`, scene at `:958`): an open cause still draws the scour
     scene, labelled "THE BED WEARS AWAY · WATER DROPS". Only the tag says "LEADING GUESS".
     (Flagged by nip-large; checked.)
   - Event log (`console.html:689`): "skeptic accepts scour 72%" on a gauge whose finding is open.
   - The saved ranker text in the Replay trace (`traces/03451500-20261108T030614228331Z.json`,
     round 2) calls an area change of 7.7 % "the substantial channel widening" and a "cleared
     control". It isn't shown on screen, but it is in `/trace`.
   - Hepco (Disagreement) and Newport (corroborated) are fine. Their wording matches their status.

5. **The engine's own "likely cause" contradicts the agents** (item 3).
   `driftwatch/modules/rating_curve/report.py:238` writes `likely_cause` and `narrative` into
   every report, and `summary_line` prints it. So `make report` and `make demo` print
   "Pigeon River near Hepco … likely datum_change" and "French Broad at Asheville … likely
   scour", and `reports/03451500.json` reads "41 % more water than rated is the direction scour
   produces". The console says Hepco is a Disagreement (best guess fill) and Asheville is open. The
   same text goes to the ranker as `m1_cause` and `m1_why` (`graph.py:107-108`), so it also
   anchors the LLM.

6. **The README still has placeholders a judge will see** (item 2). `README.md:8`
   "[cold-start time, s]" (measured: 16 s on Cloud Run, see 3), `README.md:95`
   "[Gemini eval pass count, of 13]" and "[Gemini eval wall time, s]", and `README.md:101`
   "[Mills high-flow misfit, %]".

7. **README and eval-report numbers that the code no longer gives** (item 2).
   - `README.md:34`: "159 passed". The clean clone gives **186 passed**.
   - `README.md:5`: "covers 8 USGS gauges … plus the Eno River". That reads as 9 gauges. The Eno is
     one of the 8.
   - `README.md:94` says thoth, 11 of 13, 71 s. That reproduces: my rerun on thoth gave 11/13 in
     71 s. But the committed `docs/eval_report.md:3-5` is a **laptop** run (252 s) from 00:05 UTC,
     which is before rule (b). Its Gemini column fails case 2 (`:12`) and says "not diagnosed yet"
     (`:27`), and case 12 replays an old Hepco trace (`:22`) rather than the current Replay default.
     `README.md:97` ("the two failures are cases 9 and 10") is true only for the fallback column.
   - Engine numbers: all match. Band, score, shift date, shift size (% and ft), trend and suggested
     shift for all 8, rebuilt into a temp dir. Every number in the README table at `README.md:79-86`
     agrees with the reports.

8. **Replay text and live text differ at two of the three pinned gauges** (item 4). The event
   structure is the same in both paths: same nodes, same order, same `final` and `disagreement`
   keys. The extras on the Gemini side are only `input_tokens`, `output_tokens`, `seconds`, plus
   `attempts` after a retry. The text differs:
   - Newport and Asheville Replay (`traces/replay_defaults.json`, the 22:06 runs) still open on the
     "Q = V × A" sentence. That sentence was removed as filler at 22:35, so the template and new
     runs no longer have it.
   - Asheville Replay includes the I-26 Connector "Possible lead". The template always drops it at
     the 200-word cap. Cloud Run can't produce it either, because the `Dockerfile:16-18` doesn't
     copy `data/context/`.
   - The Hepco and Newport confidences differ (fallback 40 % and 44 %, Gemini 45 % and 83 %). That
     is expected, but a judge who presses Run after Replay will see different numbers.
   - `graph.py:492`: on a narrator retry, `meta` is overwritten, so the first attempt's tokens are
     dropped from the trace totals. Asheville's Replay undercounts.

9. **`make demo` dirties a clean clone.** `Makefile:63-64` writes `reports/03459500.json` and
   `reports/03451000.json` in place. Only `generated_at` changes, but `git status` shows two
   modified files right after the README steps. `make evals` likewise overwrites the committed
   Gemini column with "[run on laptop]".

10. **Stale comments and inconsistent words a reader trips over** (item 5).
    - Band names: the console says "Potential drift" and "Drifted" (`console.html:386`, `:858`).
      The README, narration and API say "Watch" and "Stale". The score is called "trust score" on the
      card (`graph.py:87`, `console.html:858`) but "rating confidence" in the README and narration.
    - "speed" and "same flow" remain after the wording change: `README.md:54`,
      `driftwatch/api/app.py:261` (comment), `console.html:753` (comment), and 5 strings in
      `driftwatch/api/static/education.json` (`:16`, `:32`, `:76`, `:88`, `:100`). The Education
      ones are visible on screen.
    - "the agents are still checking" (`console.html:833`, `:1045`) is said of a finished run.
    - `docs/narration_status.md:20` still lists "the first sentence must state Q = V × A" as a
      guard rule. It was removed at 22:35.
    - `/gauges` returns `score: 23.799999999999997` (`app.py:286`). The console rounds it, but anyone
      reading the JSON sees it.
    - `app.py:1-13`: the docstring's route list omits `/map/{site}`.
    - `traces/fallback/03459500-20261107T165327575578Z.json` is a 16:53 trace with the old
      structure (no `disagreement` key). Nothing reads it.
    - No TODO or FIXME markers, and ruff finds no unused imports or variables. The functions only
      the tests reference (`run_sync`, `pair_measurements`, `causes_for_sign`) are fine.

## Checked and fine

`/report/{unknown}`, `/report/abc`, `/replay/00000000`, `/run/abc` → 404. Malformed trace id →
400. A well-formed but missing trace id → 404. `?pace=9`, `-1` and `nan` → 422. Path traversal
can't reach a file (the route won't match, and the id regex). `/replay` for a Trusted site with
no pin streams fine. `/report` for a site whose stored report is missing returns no trend rather
than failing (`app.py:201-208`). POST /run always ends its stream: `run_agents` emits
`run completed` or `run error` on every path (`graph.py:569-584`). Every gauge has a map layer.

## Clean-clone run (fresh clone of origin/main feeaf98, fresh venv, thoth, Python 3.13.5)

These ran while I was also reading code, but nothing heavy ran during `make test`.

| Command | Result | Time |
|---|---|---|
| `git clone https://github.com/inmang13/driftwatch.git` | ok | 32.5 s |
| `python3 -m venv .venv` | ok | 14.9 s |
| `.venv/bin/python -m pip install --upgrade pip` | ok | 9.2 s |
| `.venv/bin/python -m pip install -e ".[dev,agents,api]" httpx` | ok | 4 min 26 s |
| `make test` | **186 passed** | 7 min 48 s (pytest says 7:29) |
| `make demo` | ok; Hepco Stale 24, Swannanoa Trusted 94; leaves 2 report files modified (see 9) | 56.9 s |
| `make serve` | `/` 200 after 8.5 s; `/gauges` lists 8 | first `/gauges` about 20 s (see 3) |
| `make evals` (extra) | 11/13 fallback, the same two Eno failures | 71 s (83 s wall) |

## Safe to fix before 8:45 am (five minutes each, no logic change)

- README: fill the cold-start placeholder (about 16 s measured on Cloud Run), change "159 passed"
  to "186 passed", fix "8 gauges … plus the Eno" to "7 gauges … plus the Eno" (or "8 gauges,
  including the Eno"), change "channel area and speed" to "velocity". Fill or delete the Gemini eval
  and Mills misfit placeholders.
- `console.html:833` and `:1045`: delete "the agents are still checking".
- `education.json`: change "water speed" to "water velocity" in the 5 strings.
- Hit `/gauges` on Cloud Run a few minutes before judging, so the instance is warm (the 7:00
  watchdog does one hit already).
- Before judging, don't press Run on the 5 unpinned gauges on the instance you'll demo from. Or
  pin those 5 in `replay_defaults.json` to their committed traces, which is a data-only edit.

## Do not touch before judging

- The event-loop fix (finding 1: `asyncio.to_thread` around the sync nodes) and the Replay-pin
  logic (finding 2). Both are small, but they change the run path the demo depends on, and the
  186 tests take about 8 minutes on the Pi.
- The Asheville card and hero logic (finding 4) and the engine `likely_cause` (finding 5). These
  are wording and logic changes with test expectations attached (`tests/test_api.py`, evals case 3).
- `replay_defaults.json` for the 3 pinned gauges, and any narrator or guard rule. They were all
  tuned last night and the tests pin them.
- The Dockerfile and Cloud Run. A redeploy at 8 am is the riskiest thing on this list.
- `docs/eval_report.md`. Regenerating it on thoth overwrites the laptop's Gemini column.
