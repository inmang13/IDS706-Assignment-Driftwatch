# DriftWatch finalist pitch (3:00)

Source: the "2. Pitch" section of `docs/plan.md` (audience, numbers to say out loud, differentiation table, one-liner and the 3-minute outline). A separate `docs/pitch.md` was planned but never committed to any branch or saved on either machine, so this script is built from the plan section, with the numbers updated to the current reports. The plan's outline named Canton; that gauge is USGS 03459500 <!-- src: CLAUDE.md -->, now called the Pigeon River near Hepco.

Audience first: utility and infrastructure managers, then anyone who builds models or forecasts on gauge data. Lead with latency. Do not say the USGS flows are wrong; say the curve lags the river, and everything downstream of the gauge inherits the lag.

| Time | Beat | On screen | What you say |
|---|---|---|---|
| 0:00 to 0:25 | Hook | Hepco finding card, Stale. | "On the Pigeon River near Hepco, the field measurements taken since Helene sit 33.1 % <!-- src: docs/m2_results.md --> below the rating curve. Until that curve is redrawn, the flows computed from it run about a third high. Nobody did anything wrong. The river moved, and the curve lags it." |
| 0:25 to 0:55 | Generalize | Slide: a gauge, a meter, a pump, a model, each with its curve. | "Every streamflow number in the country is computed from a curve like this one. A USGS study of 174 <!-- src: docs/plan.md --> Virginia gauges found a median lag of about 240 to 300 days <!-- src: docs/plan.md --> between a shift starting and being entered. And streamflow is one case. Utilities run on calibrations: meters, pump curves, stage-storage tables, models. ML teams have drift monitors for their models. Nobody watches the calibrations." |
| 0:55 to 1:45 | Live demo | Console: Newport Replay, then Hepco Replay. | "Here is the French Broad near Newport. DriftWatch refits the curve, finds a step down of 42 % <!-- src: docs/dh_results.md --> after Helene, and gives the gauge a rating confidence of 30 <!-- src: docs/m2_results.md --> out of 100 <!-- src: docs/plan.md -->, with every deduction shown. Now the agents. They pull the field notes and the channel measurements, rank the causes, and a Skeptic on a different model checks the ranking. At Newport the note says fill and the numbers agree. At Hepco the note says scour, the measurements moved the fill way, and the Skeptic disagrees. It quotes the note, says why, and recommends a level survey. When the team is unsure, it says so and names the check." |
| 1:45 to 2:15 | Engine and registry | Pipeline diagram, then the Registry tab. | "Under the agents is a generic engine: get the data, fit the expected relationship, test for drift, list the likely causes. The drift test follows the change-point segmentation in ShiftHappens, rebuilt in Python, with a trend test for slow slides like the Mills River, which has drifted about 0.8 % <!-- src: docs/trend_status.md --> lower each year. Rating curves are module one. Seven <!-- src: docs/plan.md --> more are specified in the registry, from sewer meters to pump curves." |
| 2:15 to 2:40 | Evals | The eval table from the README. | "We test it like software. The eval suite passes 11 of 13 <!-- src: docs/eval_report.md --> cases with the rule-based fallback, [Gemini eval pass count, of 13] with Gemini, and no test calls an LLM. The two failures are synthetic changes on the Eno: a slow slide that the search reads as a step. We report them with the diagnosis." |
| 2:40 to 3:00 | Next and close | One-liner slide. | "Next, the same engine on meter under-registration, with a utility partner. Rating-curve tools find the shift if an expert is looking. ML-ops tools watch models and leave meters alone. DriftWatch watches any engineered relationship, explains the drift in plain English, and gives a rating confidence anyone can act on." |

## Differentiation (one slide, from plan §2)

| What exists | Does | Gap |
|---|---|---|
| Aquarius Time-Series (Xylem), WISKI (Kisters) | Rating editing, shift management, alerts | Expert-driven, vendor silo, no explanation |
| BaRatin, BaM, ShiftHappens (INRAE) | Bayesian ratings and change-point segmentation | R and Fortran, one relationship type, no explanation layer |
| USGS shift-adjusted ratings | Hydrographers apply shifts after each measurement | Manual, per gauge |
| Evidently, Arize, NannyML, WhyLabs | Drift monitoring for ML models | Software models only |
| Trinnex waterCAST, Innovyze Info360, Xylem Vue | Utility analytics platforms | Platforms; DriftWatch is the drift module they would plug in |

## If a hydrologist asks

- **Method lineage:** Darienzo et al. 2021 <!-- src: docs/plan.md --> and ShiftHappens; the exponent and offset stay fixed from the base fit, and drift slides the coefficient.
- **Sign convention:** scour pushes measurements above the curve, fill below. Hepco's note and sign disagree; that is why the Skeptic stops short of a cause.
- **Channel numbers** are evidence only. Discharge equals area times speed, so using them as predictors would leak the answer.
- **Known limits:** the single-segment rating misses the Mills River at high flows, and a step can show about one gauging late.
