# Narration status (branch m2-narration, 2026-11-07)

Both phases are done and pushed. `make test` passes (176 tests), `make demo` passes offline, and
`make evals` gives 11/13 with LLM=fallback, the same two Eno failures as on main.

## Phase A: report-voice narration

- `driftwatch/agents/narration.py` (new): the narrator facts are computed in code, plus the fixed
  sentences and the guard (`check_text`, `banned`).
- `fallbacks.narrate` builds the template from those sentences. `graph.narrator` sends the facts
  and the sentences to the LLM and checks its text. On a guard hit it retries once, telling the
  model why the text was rejected, and then falls back to the template. Every attempt and the
  narration facts go into the narrator's trace payload.
- The closing sentence is now "Rating confidence N/100 (Band).". The triage `score_display`
  ("Trust score ...") is unchanged, so the console is unaffected.
- The cap went from 120 to 200 words. Bare symbols (`%`, `=`, `×`) don't count as words. The
  fallbacks run 179–185 words.
- Guard rules: 200 words; ends on the rating sentence; banned words and patterns (rule 7, plus
  "the team" and "amount of water"); the open-cause rule, checked after removing the labelled
  note sentences and the lead; the note meaning must appear verbatim; Helene named only when
  `helene` is true, and then the Helene event sentence verbatim; the first sentence must state
  Q = V × A; the check verdict words must appear; otherwise the event sentence must give the
  measured peak or "no measured high flow explains it".
- `evals/run_evals.py`: the Asheville "no mechanism words" check now skips the labelled note
  sentences, as the spec allows. `tests/test_api.py` pins the new Hepco replay default.

### Things to know
- **Helene rule (changed 2026-11-07, replaces the 30-day window):** `helene` is true when the
  last visit before the change is before 2024-09-27 and the change visit (the first tested visit
  after it) is after it. "Tested" means the visits the drift test uses, so the Poor storm
  gaugings left out of the test don't count as visits. Newport (2024-08-19 / 2024-10-28) and
  Hepco (2024-08-22 / 2024-12-17) are true. Asheville (2025-06-03 / 2025-07-23) is false.
- **Event sentence when `helene` is true:**
  - No gauging in the gap (Hepco): "Hurricane Helene (2024-09-27) passed between the 2024-08-22
    and 2024-12-17 visits; no gauging was made during the storm."
  - **Newport differs from the spec on purpose.** Its gap holds two storm gaugings (2024-09-27
    and 2024-09-28, both rated Poor and left out of the drift test). "No gauging was made during
    the storm" next to the 91,700 cfs peak would contradict itself, so the clause names them
    instead: "...; the only gaugings during the storm were rated Poor, the largest 91,700 cfs on
    2024-09-28." To use your wording, change one line in `narration.helene_event`.
  - A non-storm gauging in the gap gets "...; no gauging was made during the storm, and the
    largest flow gauged between the visits was X cfs on D." No current site hits this case.
- The Helene sentence is fixed text. The prompt tells Gemini to copy it verbatim and the guard
  checks it word for word, because Gemini paraphrased it ("without storm gaugings") before that.
- Tests: the old-window synthetic test is kept (its cases flip: 23 days after is now false, the
  real 31-day Newport change is now true), and a new `test_helene_visit_rule` covers the rule.
- 15-point check: Newport −47.8 % vs −42.2 % (agrees), Hepco −30.9 % vs −25.6 % (agrees),
  Asheville +9.5 % vs +46.2 % (does not back up).
- Which field note gets explained: the note at the change visit if it has a fixed meaning, else
  the first "control changed" note, else the latest note with a meaning. Only Fill, Scour and
  Debris have a meaning. Other notes (Vegetation, Submerged, Clear) get no note sentence.
- "Lists of three adjectives" is a heuristic: three comma-listed words with adjective suffixes. A
  spaced hyphen is allowed because field notes are written "Debris - Light".
- The worktree has no venv of its own, so `make test`, `make demo` and `make context` were run
  from `..\AIHackathon-narration` with `PY=..\AIHackathon\.venv\Scripts\python.exe`.

## Phase B: cached event context

- `driftwatch/agents/context.py`: `load()` is the only part an agent run touches. It reads
  `data/context/<site>.json` and never searches. `make context SITE=...` runs Gemini on Vertex
  with Google Search grounding (supported in the installed langchain-google-vertexai 3.2.5).
  Three queries are built in code from the river, place, county, state and the visit window:
  storms/floods, dams/construction near the gauge, and USGS reports. A finding is kept only if a
  grounding chunk supports it. The grounding redirect is resolved to the real URL and the page's
  own `<title>` is fetched. Items whose page (title plus text) doesn't name the river or county
  are dropped. Claims and titles are cleaned of dashes, `| ? !` and parentheses.
- **Fixed after the files were made:** the first version of that filter tested the model's own
  claim, so it let everything through. It now tests the fetched page, which also drops PDFs and
  blocked pages (no text). The committed JSONs were made before this fix and then checked by
  hand (below), so a rerun of `make context` will keep fewer items.
- The evidence collector adds an `event_context` tool result, so the trace carries the URLs. The
  console has no code change; it shows the new step as a plain "event_context" row.
- Lead choice (`narration.pick_lead`): construction, then dam, then USGS report, then storm. A
  claim naming Helene is skipped unless `helene` is true (rule 4). Tests point
  `context.CONTEXT_DIR` at an empty dir, so they never see the committed files.
- Leads used now: Hepco gets the Walters Dam item (allowed, since `helene` is true for
  Hepco). Newport gets the 1960 USGS water-supply paper. Asheville gets the I-26 Connector
  bridge plans.
- The Cocke County evacuation item was taken out of `data/context/03455000.json` and moved to
  `removed_on_review` with `reviewed: false`, reason "not about the rating".

### Items I removed after checking each URL's title against its claim
| Site | Claim (as the model wrote it) | Why removed |
|---|---|---|
| 03455000 | TDOT advanced bridge construction across the French Broad River ... Newport Bypass | wbir.com returns 403 Access Denied, so the title couldn't be checked |
| 03459500 | Contractors mobilized to replace an I-40 bridge over the Pigeon River near Exit 15 | Title "All lanes of I-40 in Pigeon River Gorge now open" is about lanes reopening |
| 03459500 | Helene caused historic flooding along the Pigeon River, washing out I-40 (USACE PN) | PDF returns Access Denied, so there was no title to check |
| 03451500 | Contractors began in-water cofferdam construction ... for a municipal pipeline replacement | Title is a "$75M pump station upgrade", not a pipeline replacement |
| 03459500 | Helene caused catastrophic flooding along the Pigeon River in Haywood County (thispendentworld.com) | The page never names the Pigeon River or Haywood County; it's a general Helene blog post |
| 03459500 | The USGS deployed crews to repair damaged streamgages along the Pigeon River (USGS news) | National news release; the page never names the Pigeon River or Haywood County |
| 03455000 | Cocke County ordered downtown Newport evacuated due to erroneous reports of a dam failure | Not about the rating (Grace, 2026-11-07); marked `reviewed: false` |

Domain-only titles on PDFs ("usgs.gov", "americanrivers.org") were replaced with the document's
real title from its USGS Pubs landing page or the PDF's first page. PDFs were checked with
`pdftotext`: each one names its station or river. Each kept item has a `reviewed` field.
**Weak but kept:** atmostorm.com for Mills, an aggregator page. Its title matches its claim, but
it isn't a primary source. The Hepco Gemini trace was recorded before the last two removals, so
its evidence step still lists them. The current Hepco trace (below) was recorded after them.

## LLM=gemini narrations (Replay defaults)

`traces/replay_defaults.json` points at these runs from 22:06, made after the wording change
(flow rate and velocity; no "same flow"; directions in words). All three have the Skeptic on
`openrouter:openai/gpt-5.4-mini`, checked in each trace's skeptic events. All three narrations
are Gemini 3.8 Flash's text; none fell back to the template.
- Newport: passed on the first attempt.
- Hepco: see "Hepco: needs Grace's call" below. The Hepco text in this section is the 22:06 run,
  which is not the Replay default. Its first attempt was rejected ("the first sentence must
  state Q = V × A") and the retry passed.
- Asheville: the first attempt was rejected ("224 words > 200"); the retry passed.

**French Broad River near Newport (03455000-20261108T030614225662Z.json):**
Flow rate equals water velocity times cross-sectional area (Q = V × A); a rating curve assumes this holds at every stage. Since the 2024-10-28 visit, measurements at the French Broad River near Newport, USGS 03455000, sit 46 % below the rating, so published flows run that much too high. For a given flow rate, the river stands 0.71 ft higher than the curve predicts; at a stage of 2.70 ft it carries about 1,350 cfs (42 %) less than the curve's 3,210 cfs. The hydrographer noted "Fill control changed" on 2024-10-28. In the note's terms, gravel built up on the control (the riffle just downstream that sets the water level), so water backs up at the gauge: deeper, more area, much lower velocity. After the change, at that stage, area rose 25 % and velocity fell 58 %, so the flow rate there fell about 48 %, which agrees with the 42 % drop in measured flow rate. Hurricane Helene (2024-09-27) passed between the 2024-08-19 and 2024-10-28 visits; the storm gaugings were rated Poor, the largest 91,700 cfs on 2024-09-28. DriftWatch's agents rank fill / aggradation first (83 %); the Skeptic accepted it. Double-check: Survey the control and apply a negative shift. Rating confidence 30/100 (Stale).

**Pigeon River near Hepco (03459500-20261108T030614224292Z.json):**
Flow rate equals water velocity times cross-sectional area (Q = V × A); the curve assumes this holds at each stage. Since the 2024-12-17 visit, measurements at the Pigeon River near Hepco, USGS 03459500, sit 33 % below the rating, so published flows run too high. For a given flow rate, the river stands 0.33 ft higher than the curve predicts; at 2.33 ft stage it carries 150 cfs (26 %) less than the curve's 570 cfs. The hydrographer noted "Scour control changed" on 2024-12-17. In the note's terms, the control (the riffle just downstream that sets the water level) eroded, so a given flow rate passes at a lower water level. That disagrees with the data. After the change, at that stage, area fell 11 % and velocity fell 22 %, so the flow rate there fell about 31 %, which agrees with the 26 % drop in measured flow rate. Hurricane Helene (2024-09-27) passed between the 2024-08-22 and 2024-12-17 visits; no gauging was made during the storm. No field note confirms what changed, so the cause remains open. Double-check: Measure flow and run levels from the reference marks to the gauge before adjusting the rating. Rating confidence 24/100 (Stale).

**French Broad River at Asheville (03451500-20261108T030614228331Z.json):**
Flow rate equals water velocity times cross-sectional area (Q = V × A); curves assume this holds at each stage. Since 2025-07-23, measurements at the French Broad River at Asheville, USGS 03451500, sit 41 % above the rating, leaving published flows too low. For a given flow rate, the river stands 0.27 ft lower, carrying 440 cfs (46 %) more at 1.51 ft than the curve's 960 cfs. The hydrographer noted "Debris - Light" on 2025-07-23. In the note's terms, debris blocked the control (the riffle just downstream that sets the water level), raising the level until it clears. That disagrees with the data. After the change, at that stage, area rose 8 % and velocity rose 2 %, so the flow rate there rose about 10 %, which does not back up the 46 % rise in measured flow rate. No measured high flow explains it. Possible lead: Officials updated bridge construction plans across the French Broad River in Buncombe County for the Interstate 26 Connector project (I-26 Connector Plans Take Major Step Forward). No note confirms what changed, so the cause remains open. Double-check: Measure flow and run levels before adjusting the rating. Rating confidence 46/100 (Stale).

### Worth a look
- Hepco's ranked cause moves between Gemini runs: datum change (44 %) in the earlier run, fill
  (35 %) in this one. The Disagreement path is working as designed.
- Newport's new lead (a 1960 USGS water-supply paper) is real but says nothing about the
  rating. Its title is cut at 12 words ("... Part 3-B, Cumberland and"). Construction leads
  would be better; the search found one (Newport Bypass), but its page blocks automated reads.
- Newport's Gemini text dropped "so published flows run that much too high". The guard
  doesn't require that clause.

## Update 2026-11-07 (late): lead review, OpenRouter still blocked

- `data/context/03455000.json`: the 1960 USGS water-supply paper is marked `reviewed: false`,
  reason "not about the change". `data/context/03459500.json`: the Walters Dam item is marked
  `reviewed: false`, reason "dam is downstream of the gauge". Both stay in `items` with the flag.
- `pick_lead` now skips any item marked `reviewed: false` (the flag would do nothing
  otherwise), and skips `usgs_report` items dated before 2015 (`OLD_REPORT_BEFORE`). Undated
  reports are kept. Result: **Newport and Hepco have no lead** (Newport's other two reports are
  1990 and 2003). Asheville's lead (I-26 Connector, a construction item) is unaffected.
- **The Skeptic still can't reach OpenRouter.** Reruns at 21:43 both got 402 ("can only afford
  1970 tokens"). The key reports a $10 limit with $9.84 remaining, but the account's
  `total_credits` is 0 and the key is flagged free tier, so the credit isn't on the account this
  key belongs to. I discarded those two traces. `replay_defaults.json` still points at the
  21:22 runs listed above (Gemini narrator, rules Skeptic, with the Walters Dam lead in Hepco's
  text).

## Update 2026-11-07 22:10: wording (Grace)

- Narration: "speed" became "velocity" and "flow" became "flow rate". "Same flow" is gone. The
  level sentence now says what is compared ("For a given flow rate, the river stands X ft higher
  than the curve predicts"), and the check sentence says before vs after ("After the change, at
  that stage, area rose 8 % and velocity rose 2 %, so the flow rate there rose about 10 %, which
  does not back up the 46 % rise in measured flow rate"). Directions are in words, never signed
  numbers.
- Guard: rejects "speed", "same flow" and signed numbers like "+8 %" or "-22 %".
- Console (`console.html`, merged with main first):
  - The "What happened" boxes now read "Change in water level for a given flow rate, vs the
    curve", "Change in flow rate at X ft, vs the curve", "Change in cross-sectional area at X ft,
    before vs after" and "Change in water velocity at X ft, before vs after". Values are in
    words ("up 8 %", "440 cfs more").
  - The check line reads "Flow rate = area × velocity. At X ft, after the change compared with
    before, the area rose ...".
  - I removed the console rule that rewrote "velocity" as "water speed", and changed the hero
    caption's "same flow" and "speed" too.
  - Not changed: the Education tab (`static/education.json` still says "speed"/"same flow" in 5
    places), the triage row ("newest readings -33 % from the curve") and the trust explainer.
  - I couldn't check the layout in a browser because the Chrome extension didn't respond. The
    box labels are longer now, so they may wrap.
- The 200-word cap is tight now. The fallbacks run 194–199 words, so the template drops a
  "Possible lead" sentence at all three Stale gauges. Gemini can still fit one by tightening.
  That doesn't matter today, because none of the three has a usable lead.

## Hepco: needs Grace's call (2026-11-07 22:20), resolved by rule (b) below

**With the Skeptic back on OpenRouter, Hepco no longer produces a Disagreement.** In both new
runs (`03459500-20261108T030614224292Z.json` and `03459500-20261108T031518546663Z.json`) the
Skeptic objected once, then accepted fill on its second pass (74 % and 84 % sure). With no
Disagreement and no field note backing fill, Hepco's cause status is "open". The narration
still quotes the Scour note and says it disagrees with the data. `tests/test_api.py` expects
Hepco's Replay trace to be the Disagreement case, so for now `replay_defaults.json` keeps Hepco
on the earlier Disagreement run (`03459500-20261108T022812744003Z.json`: rules Skeptic, old
wording). Newport and Asheville use the new runs. To switch Hepco, point `replay_defaults.json`
at either new trace and update the Hepco test expectation (`test_trace_by_id_and_by_site`).

Newest Hepco narration (`03459500-20261108T031518546663Z.json`, Skeptic on OpenRouter):
Flow rate equals water velocity times cross-sectional area (Q = V × A); the curve assumes this holds at each stage. Since the 2024-12-17 visit, measurements at the Pigeon River near Hepco, USGS 03459500, sit 33 % below the rating, so published flows run too high. For a given flow rate, the river stands 0.33 ft higher than the curve predicts; at 2.33 ft it carries about 150 cfs (26 %) less than the curve's 570 cfs. The hydrographer noted "Scour control changed" on 2024-12-17. In the note's terms, the control (the riffle just downstream that sets the water level) eroded, so a given flow rate passes at a lower water level. That disagrees with the data. After the change, at that stage, area fell 11 % and velocity fell 22 %, so the flow rate there fell about 31 %, which agrees with the 26 % drop in measured flow rate. Hurricane Helene (2024-09-27) passed between the 2024-08-22 and 2024-12-17 visits; no gauging was made during the storm. No field note confirms what changed, so the cause remains open. Double-check: Measure flow and run levels from the reference marks to the gauge before adjusting the rating. Rating confidence 24/100 (Stale).

## Update 2026-11-07 22:35: Disagreement rule (b), opener removed (Grace)

- **Rule (b):** a Disagreement is emitted whenever the note at the change visit maps (through
  `causes.cause_for_note`) to a cause whose expected residual sign is opposite to the final
  cause's, whatever the Skeptic's confidence. Rule (a), under 0.6 sure plus a contradicting
  control note, still applies. `Disagreement.rule` records which one fired, and (b) wins when
  both hold.
  - For rule (b), `why_they_disagree` is `narration.note_vs_data` and `recommended_check` is the
    Skeptic's.
  - The narration conclusion reads: "DriftWatch's agents rank fill first (N %); the
    hydrographer's note says scour; the two disagree, so the cause is not settled."
- **Asheville changed too.** Its change-visit note, "Debris - Light", maps to debris, which
  lowers readings, and its final cause, scour, raises them. So under rule (b) Asheville is now a
  Disagreement instead of open. This follows the rule as written. Asheville's Replay trace
  (22:06) was made before the rule and still shows "open". To get the new behaviour on Asheville,
  rerun it, or limit rule (b) to "control changed" notes to keep it open. The open-cause tests
  now use Asheville with rule (b) switched off.
- **The Q = V × A opener is removed** as filler. The narrations now open on what was measured.
- **Hepco Replay default** is now `03459500-20261108T033244636752Z.json`: Skeptic on OpenRouter
  (objected, then disagreed at 45 %, so rule (a) would also have fired), Gemini narration first
  try, 192 words:

Since the 2024-12-17 visit, measurements at the Pigeon River near Hepco, USGS 03459500, sit 33 % below the rating, so published flows run that much too high. For a given flow rate, the river stands 0.33 ft higher than the curve predicts; at a stage of 2.33 ft it carries about 150 cfs (26 %) less than the curve's 570 cfs. The hydrographer noted "Scour control changed" on 2024-12-17. In the note's terms, the control (the riffle just downstream that sets the water level) eroded, so a given flow rate passes at a lower water level. That disagrees with the data. After the change, at that stage, area fell 11 % and velocity fell 22 %, so the flow rate there fell about 31 %, which agrees with the 26 % drop in measured flow rate. Hurricane Helene (2024-09-27) passed between the 2024-08-22 and 2024-12-17 visits; no gauging was made during the storm. DriftWatch's agents rank fill first (45 %); the hydrographer's note says scour; the two disagree, so the cause is not settled. Double-check: Survey the control section and downstream reach for deposited sediment or debris, and recheck the gauge datum against reference marks. Rating confidence 24/100 (Stale).

## Update 2026-11-07 22:45: rule (b) counts only "control changed" notes (Grace)

Rule (b) now uses the change-visit note only if its text contains "control changed". Asheville
("Debris - Light") stays **open**, which matches its Replay trace. Hepco ("Scour control
changed") stays a **Disagreement**. Covered by `test_rule_b_counts_only_control_changed_notes`.
