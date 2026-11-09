# DH results: two residual series, quality weighting, suggested shift, magnitude gate, reference mode

Run 2026-11-07 (round 3, 15:00; tables for 1 and 3 from round 2, unchanged since fixed mode did not move) on the committed snapshot, branch `pi/dh-test`. `make test` 125 passed, `make demo` green offline.
Decisions and thresholds: docs/decision_log.md, entries "dh 1" to "dh 4", "dh round 2" and "dh round 3".

**Bottom line:** the round-3 auto rule meets the expected result. The four controls (Swannanoa, South Toe, Watauga, Eno) are Trusted in both modes. Hepco and Newport are Stale in both, with the same shift date; so is Asheville. **One gauge disagrees: Mills River, Watch 73 fixed vs Trusted 90 auto** (Surprise 1). In fixed mode, Hepco and Newport show a post-Helene step larger in ft and concentrated at low flows; Asheville's step is larger in %. The magnitude gate cuts the Eno null's false alarms about 5-fold (56 % → 12 % at 80 visits).

## 1. Two residual series (fixed mode, gate on)

Shifts after the reference window, size = quality-weighted median after − before. Standardized step = |step| / robust σ of that series' reference residuals. "Low flow" = after the step, median |ft residual| in the lowest third of flows > in the top third. Gate = the smallest |size_pct| a change point needs to count as a shift. Holdout = searched measurements after the reference window.

| Site | Gauge | % series shifts | ft series shifts | % step (σ) | ft step (σ) | Larger | Low flow | Suggested shift ft (n) | Gate % | Holdout |
|---|---|---|---|---|---|---|---|---|---|---|
| 03459500 | Pigeon River near Hepco | 2024-12-17 −26 % / −0.33 ft | 2024-12-17 −26 % / −0.33 ft | 5.24 | 5.82 | ft | **True** | −0.335 (12) | 10.0 | 12 |
| 03455000 | French Broad near Newport | 2024-10-28 −42 % / −0.71 ft | 2024-10-28 −42 % / −0.71 ft | 8.13 | 11.26 | ft | **True** | −0.718 (14) | 10.0 | 14 |
| 03446000 | Mills River | none | none | — | — | — | False | −0.004 (164) | 10.0 | 16 |
| 03451500 | French Broad at Asheville | 2025-07-23 +46 % / +0.27 ft | 2025-07-23 +46 % / +0.27 ft | 9.77 | 5.13 | % | False | +0.265 (8) | 10.0 | 13 |
| 03451000 | Swannanoa at Biltmore | none | none | — | — | — | False | +0.006 (119) | 10.0 | 11 |
| 03463300 | South Toe near Celo | none | none | — | — | — | False | +0.000 (119) | 10.0 | 9 |
| 03479000 | Watauga near Sugar Grove | none | none | — | — | — | False | +0.005 (104) | 10.0 | 10 |
| 02085000 | Eno at Hillsborough | none | none | — | — | — | False | −0.001 (78) | 12.03 | 8 |

The gate removed Mills's 2019-05 −6 % step and Eno's 2022 blip (−17 / +11 %) from the % series, plus 1–3 in-window ft-series splits at each control. Because those merges lengthen the latest stable period, the suggested shift moved at Mills (n 63 → 164) and Eno (n 22 → 78); both stay near zero. No post-reference shift changed.

### Step 2 effect (quality weighting) vs the M1 numbers

| Gauge | Before | After |
|---|---|---|
| Hepco top shift | −28 % (−0.33 ft) | −26 % (−0.33 ft) |
| Newport top shift | −43 % (−0.72 ft) | −42 % (−0.71 ft) |
| Asheville top shift | +36 % (+0.27 ft) | +46 % (+0.27 ft) |
| Mills in-window blips 2016-02 (±51 %) | present | gone (they were Poor gaugings) |

## 3. Eno synthetic null, before and after the gate

The null adds N post-window visits to Eno. Each visit is a reference stage with a reference residual drawn at random, from the search series with Poor left out. No step is injected. Firing = any shift after the reference window. 50 seeds per row. Eno's gate is 12.03 % (1.5 × MdAPE 8.0 %).

| Post-window visits | No gate | Gate on |
|---|---|---|
| 20 | 18 % | 2 % |
| 40 | 40 % | 8 % |
| 80 | 56 % | 12 % |

The gate does not stop false alarms from growing with the number of looks (2 → 12 %), but it cuts them about 5-fold at every length. Eno has 8 searched post-window visits today.

## 4. Reference mode: fixed vs auto (round 3 rule)

Auto = the latest stable period of the full-history search, with its window ending the day before the newest 8 searched measurements; those 8 are the test set, plus any gauging taken the same day as the first of them. If the latest period has fewer than 20 measurements or spans less than 2 years, the previous stable period is the reference, whole, and everything after it is tested. Holdout = searched measurements (Poor left out) after the window.

| Site | Gauge | Fixed: band | Fixed: top shift | Fixed holdout | Auto window | Auto rule | Auto holdout | Auto: band | Auto: top shift | Differs |
|---|---|---|---|---|---|---|---|---|---|---|
| 03459500 | Pigeon River near Hepco | Stale 24 | 2024-12-17 −26 % (−0.33 ft) | 12 | 2004-09-08..2024-08-22 | previous | 12 | Stale 24 | 2024-12-17 −25 % (−0.31 ft) | shift size |
| 03455000 | French Broad near Newport | Stale 30 | 2024-10-28 −42 % (−0.71 ft) | 14 | 2004-09-09..2024-08-19 | previous | 14 | Stale 30 | 2024-10-28 −43 % (−0.73 ft) | shift size |
| 03446000 | Mills River | Watch 73 | none | 16 | 1934-06-07..2025-12-03 | cut latest | 8 | **Trusted 90** | none | **band** |
| 03451500 | French Broad at Asheville | Stale 46 | 2025-07-23 +46 % (+0.27 ft) | 13 | 2008-12-18..2025-06-03 | previous | 8 | Stale 46 | 2025-07-23 +48 % (+0.27 ft) | shift size |
| 03451000 | Swannanoa at Biltmore | Trusted 94 | none | 11 | 2009-10-01..2025-06-10 | cut latest | 9 | Trusted 92 | none | — |
| 03463300 | South Toe near Celo | Trusted 95 | none | 9 | 1959-01-14..2024-12-03 | cut latest | 9 | Trusted 95 | none | — |
| 03479000 | Watauga near Sugar Grove | Trusted 95 | none | 10 | 1984-05-16..2025-05-07 | cut latest | 9 | Trusted 95 | none | — |
| 02085000 | Eno at Hillsborough | Trusted 91 | none | 8 | 2011-07-22..2025-09-15 | cut latest | 8 | Trusted 88 | none | — |

Expected vs got: the four controls are Trusted in both modes ✔. Hepco and Newport are Stale in both with the same shift date (2024-12-17, 2024-10-28) ✔. Asheville is Stale in both ✔. At those three gauges the shift size moves by 1–2 points between modes; the date does not. The auto test set holds 9 measurements at Swannanoa, South Toe and Watauga, because a second gauging was taken on the same day as the first of the newest 8.

Round 2's rule (the most recent period ending at least 8 measurements before the latest) turned Swannanoa, Watauga and Eno Stale by falling back to windows from 2004–09, 1940–84 and 1999–2002. Round 3 fixes that by cutting the latest period instead of skipping it.

## Surprises

1. **Mills River disagrees: Watch 73 in fixed mode, Trusted 90 in auto.** In the full-history search Mills is one stable period from 1934 to now. A rating fitted on that 91-year window puts the newest 8 gaugings at −4.2 %. The 2012–2024 fixed rating puts them at −11.6 %, which costs 16.2 points. The "Debris - Moderate" note on the latest visit costs 8 points in both modes. Neither band is clearly wrong: the fixed rating is tighter, so it sees a recent low reading; the long window absorbs it into the gauge's normal scatter. This is the gauge to look at if auto becomes the default.
2. **Auto windows reach far back.** Mills 1934, South Toe 1959, Watauga 1984. The base rating then averages decades of channel. It works on these gauges, but the fixed windows are deliberately recent.
3. **The low-flow clue fires at both hero gauges and nowhere else** (unchanged). At Hepco and Newport the step is larger in ft and concentrated at low flows, the pattern of a change in the control's zero-flow height. At Asheville the whole curve slid.
4. **Gate merges reach the suggested shift.** Merging small in-window change points lengthens the latest stable period at Mills and Eno, so the suggested shift is now computed over 164 and 78 gaugings instead of 63 and 22. It is still about 0 ft at both.
5. **The ft series splits more than the % series inside the reference windows**, and the gate removes most of those splits. The ft lists are evidence to read beside the % series, not a second alarm.

## Not done / limits

- `reference_mode` is reachable only from `build_report(..., reference_mode="auto")`. The CLI and the API were outside the files this job could edit, so `make report` always runs fixed.
- Nothing in `driftwatch/agents/` or `driftwatch/api/` reads the new Report and DriftResult fields yet.
- `reports/*.json` were regenerated for all 8 gauges (fixed mode). They are in their own commits and can be dropped.
