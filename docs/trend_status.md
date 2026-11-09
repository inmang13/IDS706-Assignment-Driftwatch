# Trend status — slow drift in the latest stable segment (2026-11-07)

`driftwatch/modules/rating_curve/trend.py`, `site_trend(ds, rel, drift)` → `fit_trend(...)`.
Fixed reference mode, snapshot source. Window = the change-point search series (Poor left out,
Helene-excluded and stage ≤ e left out) inside the latest stable period of the % series, i.e.
after the last accepted shift; a gauge with no accepted shift uses its whole series from the
reference start to the latest gauging. Slope = weighted Theil–Sen of residual % vs years
(pair weight w_i·w_j, `Measurement.weight`); CI = 95 % bootstrap, 2,000 resamples, seed 7;
p = two-sided Mann–Kendall. Significant = p < 0.01 **and** |slope| ≥ 0.75 %/yr **and** the CI
excludes 0. No fit below 12 measurements or 3 years. Negative = the gauge measures less flow
each year than the curve predicts ("lower").

| Site | Window | n | Slope (%/yr) | 95 % CI | p | Significant |
|---|---|---|---|---|---|---|
| 03459500 Pigeon R. nr Hepco | 2024-12-17 .. 2026-08-07 | 12 | – | – | – | no fit (1.63 yr < 3) |
| 03455000 French Broad nr Newport | 2024-10-28 .. 2026-10-19 | 14 | – | – | – | no fit (1.97 yr < 3) |
| 03446000 Mills River | 2012-01-11 .. 2026-10-07 | 164 | −0.84 | −1.10 .. −0.60 | 3.9e-13 | **yes, lower** |
| 03451500 French Broad at Asheville | 2025-07-23 .. 2026-10-16 | 8 | – | – | – | no fit (8 < 12) |
| 03451000 Swannanoa | 2012-02-13 .. 2026-10-02 | 119 | −0.27 | −0.71 .. +0.09 | 0.053 | no |
| 03463300 South Toe nr Celo | 2012-02-09 .. 2026-10-14 | 119 | +0.17 | −0.18 .. +0.42 | 0.64 | no |
| 03479000 Watauga nr Sugar Grove | 2012-01-19 .. 2026-10-14 | 104 | −0.20 | −0.68 .. +0.20 | 0.17 | no |
| 02085000 Eno at Hillsborough | 2015-03-04 .. 2026-10-15 | 78 | −0.95 | −1.66 .. −0.10 | 0.012 | no (p only) |

Mills text: "Readings have drifted about 0.8 % lower each year since 2012 (164 measurements)."

## Against the expected outcome

- **Matches.** Mills significant and lower; Swannanoa, South Toe, Watauga and Eno not significant.
- **Mills is near the slope floor.** −0.84 %/yr clears 0.75, but the CI's upper end (−0.60) is
  below it, so the floor itself is not robustly cleared. The p-value is not in doubt.
- **Eno is a near miss, not a clear null.** Slope −0.95 %/yr and the CI excludes 0; it is
  "not significant" only because p = 0.0118 is just over 0.01. A slightly looser alpha
  (0.02) would flip it. Worth knowing before anyone tunes the rule.
- Hepco, Newport and Asheville have too little post-shift record for a trend (by design;
  their story is the step, not a slope).
- The no-shift windows run past the reference end (2024-09-25; Eno 2025-07-06), so most of
  each window is the data the base rating was fitted on. A fixed b and e with one a cannot
  absorb a time trend, so the slope still shows, but it is a within-fit trend, not a holdout test.

## Tests (`tests/test_trend.py`, offline)

−1.5 %/yr + noise (sd 5, n 60, 12 yr) → significant, slope within 0.4; flat noise, 200 seeds
(n 20, 5 yr, sd 8) → 0 / 200 significant (limit 3 %); < 12 points or < 3 years → None; same
input → identical result; weights pull the slope toward heavy points; Hepco/Newport → None.
`make test`: 152 passed. On the Orange Pi one fit is ~0.5 s at n 30 and ~25 s at n 164
(Mills; the bootstrap is O(n²) per resample).
