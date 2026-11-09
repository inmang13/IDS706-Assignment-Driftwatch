# DriftWatch eval report

Generated 2026-11-08 13:28 UTC by `make evals` on DESKTOP-4F7F34V (AMD64). Cases: `evals/cases.yaml`; runner: `evals/run_evals.py`.

**LLM=fallback: 11/13 pass**, 289 s total. Each cell gives pass/fail, the case's wall time, and what was checked.

Cases 4 and 9-13 never call an LLM (deterministic report, synthetic data, replay), so their result is the same in every column. The LLM=gemini column is filled by `make evals LLM=gemini` on the laptop (needs the Vertex credentials).

| # | Case | LLM=fallback | LLM=gemini |
|---|---|---|---|
| 1 | Newport - Stale, fill, cites the field note | PASS (0.3 s) band Stale (want Stale); cause fill (0.44); 'Fill control changed' cited as fill evidence | PASS (37.2 s) band Stale (want Stale); cause fill (0.82); 'Fill control changed' cited as fill evidence |
| 2 | Hepco - Stale, Disagreement against the scour note | PASS (0.4 s) band Stale (want Stale); Disagreement yes; field note 'Scour control changed' (2024-12-17); best guess fill | PASS (59.1 s) band Stale (want Stale); Disagreement yes; field note 'Scour control changed' (2024-12-17); best guess fill |
| 3 | Asheville - Stale, cause open, no mechanism named | PASS (0.7 s) band Stale (want Stale); cause_status open; no mechanism words | PASS (154.0 s) band Stale (want Stale); cause_status open; no mechanism words; 1 node(s) fell back to rules |
| 4 | Mills - Watch, significant lower trend, no step | PASS (2.0 s) band Watch (want Watch); 0 shift(s) in the whole series; trend -0.84 %/yr, p 3.9e-13, CI -1.10..-0.60, significant=True | same as fallback (no LLM) |
| 5 | Swannanoa - Trusted, no cause | PASS (0.3 s) band Trusted (want Trusted); no cause named | PASS (7.4 s) band Trusted (want Trusted); no cause named |
| 6 | South Toe - Trusted, no cause | PASS (0.4 s) band Trusted (want Trusted); no cause named | PASS (10.4 s) band Trusted (want Trusted); no cause named |
| 7 | Watauga - Trusted, no cause | PASS (0.4 s) band Trusted (want Trusted); no cause named | PASS (7.6 s) band Trusted (want Trusted); no cause named |
| 8 | Eno - Trusted, no cause | PASS (0.2 s) band Trusted (want Trusted); no cause named | PASS (7.3 s) band Trusted (want Trusted); no cause named |
| 9 | Eno + synthetic +25 % step at 2025-07-01 - fires | **FAIL** (0.1 s) no positive shift near 2025-07-01; shifts: 2022-09-06 -17 %, 2022-11-28 +24 % | same as fallback (no LLM) |
| 10 | Eno + synthetic -1.5 %/yr slope - trend fires, no step | **FAIL** (0.2 s) 1 shift(s) in the whole series; trend -1.41 %/yr, p 0.54, CI -4.99..+8.21, significant=False | same as fallback (no LLM) |
| 11 | Eno flat (resampled reference residuals, seed 0) - 0 shifts | PASS (0.4 s) 0 shift(s) in the whole series | same as fallback (no LLM) |
| 12 | Replay determinism | PASS (0.1 s) two fallback runs identical; 03459500-20261108T033244636752Z.json: 21 events replay identically twice | same as fallback (no LLM) |
| 13 | Swannanoa + synthetic +25 % step at 2025-01-01 - fires | PASS (0.2 s) shift 2025-06-11 +31.0 % (+0.14 ft) | same as fallback (no LLM) |

## Why the failures fail

- **9. Eno + synthetic +25 % step at 2025-07-01 - fires:** Eno's own recent gaugings already sit about 10 % below the rating, so the +25 % step lands them only about +10-15 % above it, and there are 8 searched gaugings after 2025-07-01. At penalty 50 and Eno's scatter, 8 points at that size don't pay for a change point (no shift at 2025-07 even with the gate off). The search splits Eno's 2022 blip instead. Gauge stays Trusted.
- **10. Eno + synthetic -1.5 %/yr slope - trend fires, no step:** The trend method does see the slope: fitted over the whole uncut series it gives -2.5 %/yr, p 2e-7, significant (the injected -1.5 plus Eno's own -0.95). But the slope pushes Eno's 2022-09 blip over the shift gate, so the change-point search reports a -16 % step there; the trend then only fits the 4 years after it and comes out non-significant. A slow slide gets read as a step.

## How the synthetic cases are built

- **Steps (Eno, Swannanoa):** every gauging on or after the step date (Eno 2025-07-01,
  Swannanoa 2025-01-01) has its discharge multiplied by 1.25. The check accepts a positive
  shift dated on or after the step date and at or before the 2nd searched gauging on or after
  it. (Eno's reference window ends 2025-07-06; no searched gauging falls between the two dates,
  so none of its step is in the fit. Swannanoa's window ends 2024-09-25, before its step.)
- **Slope:** every Eno gauging from the reference start (2015-01-01) on has its discharge
  multiplied by 1 - 0.015 x years since then. It adds to Eno's own slope (-0.95 %/yr, not
  significant on the real data).
- **Flat:** every Eno gauging from the reference start on gets Q = rating(H) x a reference
  residual drawn with replacement (seed 0, fixed before running). Same dates and stages, no
  step, no slope. One seed is a smoke test; the decision log records the change-point search's
  false-alarm rate across seeds.
- **Replay:** two fallback runs on Hepco must agree on the final call, rankings, objections,
  verdict and narration; Hepco's saved Replay trace (`traces/replay_defaults.json`) must replay
  the same events twice, in seq order.
