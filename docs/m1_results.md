# M1 results — what the drift engine says about the 8 gauges

*Pi job #1, built overnight 2026-11-06 from the committed snapshot (offline, no LLM). Numbers
re-run 2026-11-07 on branch m1-fixes (error cap 40 → 50, exact-only pairing, and the other review
fixes in `docs/decision_log.md`).*

## Verdict

**M1 complete.** The two hero gauges come out
**Stale**, each with a cause. The three controls come out **Trusted** and no cause gets named for
them. Mills River lands on **Watch**, which is what the plan expected. Asheville is now **Stale**
(it was Watch under the old 40-point error cap).

- **Newport (03455000) is the safe hero.** The river has carried about 43 % less water than the
  rating says since late October 2024. The field note says "Fill control changed", and the
  channel data agrees.
- **03459500 is not Canton.** It is *Pigeon River near Hepco*. It is clearly Stale (−28 %), but
  **its sign disagrees with its "scour" field note.** Details below.

## The table

"Off by" is how far real measured flow sits from what the gauge's rating predicts.
−28 % means the river actually carried 28 % *less* water than the rating says, so the flow
the gauge publishes is too high.

| Site | Station (USGS name) | Band | Score | Shifts found since the reference window | Median off by, after 2024-09-26 |
|---|---|---|---|---|---|
| 03459500 | Pigeon River near Hepco, NC | **Stale** | 24 | 2024-12-17: −28 % (−0.33 ft) | **−28.5 %** (18 visits) |
| 03455000 | French Broad River near Newport, TN | **Stale** | 30 | 2024-10-28: −43 % (−0.72 ft) | **−42.3 %** (15) |
| 03446000 | Mills River near Mills River, NC | Watch | 73 | none | −10.5 % (16) |
| 03451500 | French Broad River at Asheville, NC | **Stale** | 46 | 2025-07-23: +36 % (+0.27 ft) | +31.6 % (15) |
| 03451000 | Swannanoa River at Biltmore, NC | Trusted | 94 | none | +2.8 % (11) |
| 03463300 | South Toe River near Celo, NC | Trusted | 95 | none | −1.2 % (10) |
| 03479000 | Watauga River near Sugar Grove, NC | Trusted | 95 | none | +2.2 % (12) |
| 02085000 | Eno River at Hillsborough, NC | Trusted | 91 | none | −7.6 % (17) |

Likely causes (simple rules, no AI yet): Newport **fill**, Hepco **datum change / rebuild**
(the rule fires because the note and the sign disagree), Mills **debris** (the latest visit says
"Debris – Moderate"), Asheville **scour** (no note, positive sign). None for the four Trusted
gauges.

Where the points went: both hero gauges lose the full 50 for error, plus 15 for an open
"control changed" note. Asheville loses the full 50 for error and 4 for quality. Hepco also loses 11 because most of its recent measurements are rated
Poor or Fair. Every deduction and its reason is in `reports/<site>.json`.

Older shifts inside the reference window, kept out of the table because the base rating already
absorbs them: Mills had a 7-measurement blip in early Feb 2016 (−51 %, back within a week) and a
small −7 % step in May 2019. Eno had a −44 % dip from Sept–Nov 2022 (6 measurements) that
recovered.

## Does Hepco's sign disagree with its "scour" note? **Yes.**

Scour deepens the channel, so the same water level should carry *more* water (a positive
number). Hepco shows **28 % less**. That is what fill or something backing the water up does,
not scour.

The channel measurements give a hint (evidence only, not used in the score). *These channel
figures were computed by hand from the snapshot; they are pending the M2 evidence tool
(`channel_geometry_trend`), which will recompute them.* At the same water
level, the flow area after Helene is about the same as before (−5 %), but the water moves
**about 24 % slower**. So the measuring section did not shrink. Something downstream is likely
holding the water back, such as gravel piled on the control or debris. A gauge datum change would
mostly show up as a change in area, and it doesn't. The scour note may describe the measuring
section, which was wider on the Dec 2024 visit (136 ft vs about 120 ft before), rather than the
control. **Pitch Hepco as "the note says scour, the numbers say something is backing the water
up." That is a good story for the skeptic agent. Don't pitch it as a clean scour example.**

For comparison, Newport's channel data (also hand-computed, pending the M2 evidence tool) shows
area **+35 %** and speed **−51 %** at the same water level: a deeper, slower pool behind a raised control. That fits "Fill control changed"
well.

## Surprises

1. **Asheville is Stale (46) now that the error cap is 50.** Under the old cap of 40 it could
   not fall below 50 while losing almost nothing else, so it read Watch while 32–36 % off. Grace
   set the cap to 50 on 2026-11-07. Its shift still starts in **July 2025**, ten months after
   Helene, not at the storm; the first visits after the flood were close to the rating.
2. **Eno's rating is twice as noisy as the mountain gauges** (normal scatter 8 % vs 3–5 %). A
   plain fit missed the "< 10 %" test (10.7 %). A robust fit that stops a few odd low-flow
   measurements from bending the curve passes at 8.0 %. The trust score measures each gauge
   against its own normal scatter, so Eno is not marked down for being Eno.
3. **The change-point setting was easy to pick.** Any penalty from 25 to 150 gives the
   required answer (Eno and Swannanoa quiet after Helene, Newport fires). I used 50.
4. **Pairing is exact-match only.** The "nearest within 2 h" fallback is gone (it never fired
   on the snapshot). Six discharges at three sites are now dropped because two stage readings on
   the same visit and time disagree; all are from before 1990, outside every reference window.
5. **Station names:** 03459500 is Hepco and 03463300 is South Toe near Celo (already in the
   decision log). All output uses the USGS names. The site IDs were left alone.

## How to reproduce

`make test` (60 tests, about 5 s on the laptop) · `make demo` · `make report SITE=03455000`.
All 8 sites: `.venv/bin/python -m driftwatch.cli report`. Choices the plan left open are in
`docs/decision_log.md`, each dated 2026-11-06.
