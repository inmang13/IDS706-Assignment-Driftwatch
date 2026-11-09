# M2 results: what the agent team says about the 8 gauges

*Branch `m2-agents`, 2026-11-07. Gemini traces in `traces/` are from 12:12 pm–1:04 pm. Ranker and
narrator ran on Vertex `gemini-3.8-flash`; the skeptic ran on OpenRouter `openai/gpt-5.4-mini`.
No node fell back to the rules in any committed trace. `make test` and `make demo` use
`LLM=fallback`.*

## Replay default and the first-review rule (1:04 pm)

- **Replay default for Hepco: run 4** (`03459500-20261107T180218430129Z.json`), set in
  `traces/replay_defaults.json`. It shows the full sequence Grace asked for: one objection, a
  revised ranking, then a Disagreement.
- **`prompts/skeptic.md` now fixes the order.** On the first review, a top cause that contradicts
  a "… control changed" note gets exactly one `insufficient_evidence` objection. A Disagreement
  comes only on the second or later review. Run 4 followed this. Run 3 had gone straight to
  Disagreement.
- **Gemini is live from `.env`.** No WARNING in the run 4 or Newport traces, and no shell override
  this time.
- **The revision went the "wrong" way.** In round 2 the ranker could see the channel numbers
  (speed −22 %, area −11 %, a pattern that favours fill). It still moved *from* fill 0.42 *to*
  datum change 0.45. The skeptic's Disagreement then says why the numbers point elsewhere. So the
  demo is honest: the team ends uncertain and names the check that would settle it.

## What changed since the morning run

- **Skeptic control-note rule** (Grace, 12:10). If the top cause contradicts a hydrographer's
  "… control changed" note, the skeptic objects once and asks for the evidence that outweighs the
  note.
- **Disagreement verdict** (12:45). On the skeptic's final pass, if its confidence is under 0.6
  *and* a control note names a different cause, it returns `disagree` with a best guess, the note
  verbatim, why they disagree, and a recommended check. The narrator renders it as best guess → note
  → why → "Double-check: …".
  - The code, not the model, fills the note and its date from the field records.
  - A low-confidence gauge whose notes agree with the cause, or that has no control note at all,
    gets an ordinary accept. Fallback Newport (fill 0.44, "Fill control changed") is one example.
  - **The console's finding card doesn't exist yet (M3).** The four fields are in the skeptic and
    narrator trace payloads (`disagreement`, `parts`), ready for it.
- **Ranker sees the channel numbers after an objection.** The first round stays blind to them.
- **Narrator.**
  - The direction words ("above/below the rating", "too high/too low") are computed in code and
    must appear verbatim.
  - The output is structured (direction, confidence word, cause or disagreement, action, score
    sentence, text) and checked field by field. Anything off falls back to the template.
  - It only gets listed facts: visit recency, visits in 12 months, latest control note, and the
    residual with its direction.
  - It may not describe mechanisms or mention anything outside its facts. "Confident" requires
    0.8 or higher.
- **Missing credentials** no longer raise. Every LLM node falls back to the rules with a WARNING in
  the trace.

## Hepco: three Gemini runs

Key: each round is the ranker's top cause and confidence, followed by what the skeptic did.

| Run | Prompts in force | Round 1 | Skeptic | Round 2 | Skeptic | Round 3 | Skeptic | Final | LLM calls | Wall |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 (12:12) | control-note rule | datum change 0.46 | objects (note says scour) | datum change 0.45 | accepts | — | — | **datum change 0.45** | 5 | 58 s |
| 2 (12:13) | control-note rule | datum change 0.45 | objects (note + backwater) | fill 0.45 | objects | inconclusive 0.45 | accepts | **inconclusive 0.45** | 7 | 263 s |
| 3 (12:47) | + Disagreement, + channel after objection | datum change 0.50 | **disagrees** (confidence 0.5) | — | — | — | — | **datum change 0.50, Disagreement** | 3 | 29 s |
| **4 (1:02, replay default)** | + first-review order, + structured narrator | fill 0.42 | objects (insufficient evidence: the note says scour) | datum change 0.45 | **disagrees** (confidence 0.45) | — | — | **datum change 0.45, Disagreement** | 5 | 80 s |

**Run 4's narration (replay default):** "Recent field measurements sit 33.1 % below the rating, so
published flows are about that much too high since 2024-12-17. The best guess is an uncertain datum
change. The field note from 2024-12-17 reads "Scour control changed", but they disagree because
scour normally pushes residuals positive, while measurements are below the rating and velocity
dropped more than area. Double-check: Run a level survey from the bench mark to the gage and
inspect the control for scour/fill displacement and any shifted reference marks. Trust score
24/100 (Stale)."

Gemini's first pick moves between fill (this morning, run 4) and datum change (runs 1–3). It is
not deterministic at temperature 0. The final cause is never plain scour.

**Eval case (M5):** use "Hepco final cause is not scour". "Hepco → fill" fails with Gemini, and
"Hepco → skeptic objects" passes on runs 1, 2 and 4.

## Gemini run, per gauge (latest trace each)

Key: **Final cause** is the team's answer after the skeptic, and **conf.** is the ranker's
confidence in it (0–1). **Objections** counts the times the skeptic sent the ranker back. **Tokens**
are input + output across all LLM calls. **Wall** is seconds for the whole run, including the M1
engine. The **trace time** shows which prompt version produced it: before or after 12:54 (B/C).

| Site | Gauge | Band (score) | Final cause | Conf. | Objections | Tokens | Wall | Trace time |
|---|---|---|---|---|---|---|---|---|
| 03459500 | Pigeon R near Hepco (run 4) | Stale (24) | datum change + Disagreement | 0.45 | 1 | 12,643 + 1,696 | 80 s | 1:02 |
| 03455000 | French Broad near Newport | Stale (30) | fill | 0.75 | 0 | 7,291 + 843 | 29 s | 1:03 |
| 03446000 | Mills R | Watch (73) | debris | 0.55 | 0 | 5,930 + 708 | 24 s | 12:20 |
| 03451500 | French Broad at Asheville | Stale (46) | scour | 0.78 | 0 | 6,704 + 760 | 24 s | 12:55 |
| 03451000 | Swannanoa at Biltmore | Trusted (94) | none (straight to narrator) | — | — | 1,096 + 170 | 13 s | 12:55 |
| 03463300 | South Toe near Celo | Trusted (95) | none | — | — | 1,093 + 177 | 11 s | 12:55 |
| 03479000 | Watauga near Sugar Grove | Trusted (95) | none | — | — | 1,097 + 179 | 11 s | 12:55 |
| 02085000 | Eno at Hillsborough | Trusted (91) | none | — | — | 1,096 + 171 | 13 s | 12:55 |

Gemini latency swings a lot: Newport took 88 s on one pass and 22–29 s on others. Mills' trace (12:20) predates the structured narrator; every other gauge's latest trace uses it.
**Update 1:32 pm (M3):** Mills re-run with Gemini (`03446000-20261107T183210809638Z.json`): debris 0.52, no objections, 6,994 + 756 tokens, 43 s, structured narrator, no fallbacks. Newport ran live from the console at 1:30 pm (`03455000-20261107T183044853720Z.json`): fill 0.78, skeptic accepted at 0.86, 7,262 + 817 tokens, 27 s.

## Fallback run (`LLM=fallback`), for comparison

| Site | Final cause | Conf. | Skeptic |
|---|---|---|---|
| Hepco | fill | 0.60 | **objected once.** The first pick was datum change. The skeptic said "the water moves much slower while the section barely changed (area −11 %, speed −22 %)… fill or backwater on the control", and the ranker switched to fill. On its final pass the skeptic returns a **Disagreement**: best guess fill at 0.40 (its 0.60 less 0.2 because the "Scour control changed" note contradicts it). It then recommends surveying the control for deposited gravel and confirming the datum. |
| Newport | fill | 0.44 | accepted: the note agrees, so no Disagreement |
| Mills | debris | 0.67 | accepted |
| Asheville | scour | 0.50 | accepted |
| 4 Trusted gauges | none | — | not run |

The fallback gives Newport lower confidence than Gemini does. Its debris and vegetation notes
each take a share.

## Channel geometry (`channel_geometry_trend`)

Key: each row compares channel measurements before and after the gauge's shift date, at the
same water level (the median post-shift stage). **Area** is the flow area of the measuring section
and **speed** is mean velocity, both as % change after vs before. **n** counts the channel
measurements used on each side. These numbers are evidence only and never go into the rating.

| Gauge | Split at | n before / after | At stage | Area | Speed | Median width before → after |
|---|---|---|---|---|---|---|
| Hepco | 2024-12-17 | 101 / 18 | 2.33 ft | **−11.3 %** | **−22.1 %** | 119 → 124.5 ft |
| Newport | 2024-10-28 | 80 / 15 | 2.70 ft | **+25.2 %** | **−58.3 %** | 375 → 382 ft |
| Asheville | 2025-07-23 | 116 / 10 | 1.51 ft | +7.7 % | +1.7 % | 303 → 312.5 ft |
| Mills | 2024-09-26 (no shift; storm date) | 162 / 16 | 1.97 ft | +22.5 % | −25.9 % | 69 → 69.8 ft |

**These replace the hand-computed numbers in `m1_results.md`.** The hand numbers were Hepco
area −5 % / speed −24 % and Newport +35 % / −51 %. The direction and the story are the same: at both
hero gauges the water slows much more than the section changes. The pitch should use the tool's numbers.

**Don't use channel % as a drift signal on its own.** Swannanoa (Trusted, rating held) also
shows area +12 % and speed −30 % after the storm. South Toe shows area +170 % (its median width
went from 79 to 103 ft, which looks like the crews measured at a different section after the
flood). The channel numbers help pick a *cause* once the rating has shifted. They don't detect
drift.

## Narration notes

- **Correction to my earlier note:** only Swannanoa's direction was reversed (it read "higher than
  the rating" while it sits 7 % *above*, so published flows are slightly low). South Toe's "1.2 %
  above the rating" was correct: its recent median is +1.2 %. The −1.2 % I compared it against was
  the M1 post-Helene median.
- With the facts-only narrator (12:55), all 4 Trusted narrations and Asheville's passed the
  structured check on the first try and give the direction correctly. They now read like data
  ("6 visits in the last 12 months, 23 days since the last visit, latest control note Clear")
  instead of reassurance.
- Watauga and Eno state the residual twice, once in the required direction sentence and once as
  "a recent median residual of…". Two say "median residual", which is jargon for a manager. Both
  are tone edits in `narrator.md` if you want them.

## Problems found and fixed during the run

- The OpenRouter skeptic crashed with "Event loop is closed" on 2 gauges when each site ran in
  its own event loop. The CLI now runs every site in one loop.
- Vertex returned 429 (rate limited) once per pass. Retries went from 1 to 3. The node fell back to
  the rules cleanly when it happened, and the run still finished.
- Gemini wrote "23.8/100" where the guard expected "24". The narrator now gets an exact score
  sentence to end on, and the guard accepts either form.
- On an early pass the LLM skeptic flip-flopped on Hepco (fill → debris → fill) and labeled both
  objections "sign mismatch" when the signs matched. It now sees its earlier objections and is told
  that choosing between fill, debris and vegetation is not an error. A code guard relabels a false
  "sign mismatch".

## How to reproduce

`make test` · `make demo` (fallback, offline) · `make run SITE=03455000 LLM=gemini` (needs
`.env` credentials) · replay a trace: `python -c "from driftwatch.agents.trace import replay;
[print(e.node, e.status) for e in replay('traces/<file>.json')]"`.
