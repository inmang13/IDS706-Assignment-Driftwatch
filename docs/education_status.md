# Education status: "How rivers change their ratings" (2026-11-07)

`driftwatch/api/static/education.json` holds 8 entries for a console tab aimed at a reader with no
hydrology background. Nothing reads the file yet; the console tab itself is not built.

Sources: `docs/m2_results.md`, `docs/dh_results.md`, `docs/trend_status.md`, `reports/*.json`
(fixed reference mode, snapshot). Every number in the JSON comes from one of these.

| id | looks_like | sign | typical_size | real_example |
|---|---|---|---|---|
| scour | step_up | + | [unknown] | 03451500 Asheville, +46 % (0.27 ft) from 2025-07-23 |
| fill | step_down | - | [unknown] | 03455000 Newport, 42 % lower (0.71 ft) from 2024-10-28 |
| debris | dip_recover | - | [unknown] | 03446000 Mills, 11.6 % lower, "Debris - Moderate", no step |
| vegetation | seasonal | - | [unknown] | null |
| flood | step_down | ± | 26 % to 42 % lower (Hepco, Newport) | 03459500 Hepco, 26 % lower (0.33 ft) from 2024-12-17 |
| datum_change | step_none | ± | [unknown] | null |
| dam | step_flip | ± | [unknown] | null |
| gradual_drift | slope | ± | [unknown] | 03446000 Mills, about 0.8 %/yr lower since 2012 |

## Judgment calls to review

- **typical_size is a range only for flood.** It is the one cause with two snapshot gauges behind
  it (Hepco 26 %, Newport 42 %, both fixed-mode shift sizes from `dh_results.md`). Every other cause
  has at most one gauge, which is a single value, not a range, so it reads `[unknown]`.
- **Flood is drawn as step_down.** Its sign is ± (a flood can scour or fill), but both Helene
  gauges stepped down, so the picture matches the example.
- **Asheville as the scour example.** The report's likely cause is scour and the sign fits, but no
  field note backs it and the channel numbers are weak (area +7.7 %, speed +1.7 %). The text calls
  it "DriftWatch's leading guess, not a confirmed cause". Drop it to null if that is too soft.
- **Hepco as the flood example, not the datum-change example.** Its cause is disputed (note says
  scour, sign says otherwise; Gemini ends on datum change with a Disagreement). Channel area and
  speed both changed there, so it does not fit "step with no channel evidence". The text says the
  cause is in dispute.
- **Mills appears twice**: debris (latest-visit note, recent 11.6 % low, Watch) and gradual drift
  (trend_status: −0.84 %/yr, significant). Both are in the repo's own results. They are different
  readings of the same gauge, and that tension is worth knowing; trend_status notes the slope barely
  clears the 0.75 %/yr floor. The debris example has no recovery on record, so it shows the
  "dip" half only.
- **Dam entry** uses no real-world site or number, as asked.
- `sign` uses "-" (ASCII hyphen) and "±"; `json.tool` writes ± as `±`, which is the same string.

## Checks

- `.venv/bin/python -m json.tool driftwatch/api/static/education.json`: valid, 8 entries.
- No em dashes, en dashes, exclamation marks or emoji; every % and ft is spaced from its number.
- `make test`: 152 passed.
