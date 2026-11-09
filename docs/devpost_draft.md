# DriftWatch: drift monitoring for the relationships water systems run on

## Inspiration

Every streamflow number the USGS publishes is computed. A gauge records the water level, and a rating curve converts it to discharge. Hydrographers measure the flow by hand on field visits and shift the curve when the river changes. A USGS study of 174 <!-- src: docs/plan.md --> Virginia gauges found a median lag of about 240 to 300 days <!-- src: docs/plan.md --> between a shift starting and being entered, through 2001 <!-- src: docs/plan.md -->.

Hurricane Helene changed the channels in western North Carolina in September 2024. It set 18 <!-- src: docs/plan.md --> provisional flood records in the state and left more than 40 <!-- src: docs/plan.md --> gauges needing indirect measurements. On the French Broad River near Newport, TN (USGS 03455000 <!-- src: CLAUDE.md -->), the field measurements taken after the storm sit 42 % <!-- src: docs/dh_results.md --> below the old curve. ML teams have drift monitors for their models. Engineers who rely on calibrated physical relationships have none.

## What it does

DriftWatch reads the USGS field measurements for a gauge, refits the rating curve on a baseline period, and tests whether the newest measurements have moved off it. It looks for two kinds of change: a step, found by a change-point search on the residuals, and a slow slide, found by a trend test. It reports each change in feet of stage and percent of flow and gives the gauge a rating confidence from 0 to 100 <!-- src: docs/plan.md -->, with every deduction and its reason printed.

When a gauge has moved, a team of five agents explains why. An evidence collector gathers field notes, channel area and water speed, and flood dates. A cause ranker weighs scour, fill, debris, vegetation and a datum change. A Skeptic on a different model family checks the ranking and can send it back or record a Disagreement. A narrator writes a short finding for a utility manager and names the check that would settle it.

You can watch the agents work live in the console or replay a saved run. An Education tab explains each way a river changes its rating.

## How we built it

The engine is a Python package. It pairs each discharge with the mean gage height from the same visit, fits a weighted power law with the exponent and offset held fixed, runs a PELT change-point search with a per-gauge size gate, and fits a weighted Theil-Sen trend with a Mann-Kendall test. The method follows the segmentation idea behind BaRatin and ShiftHappens (Darienzo et al. 2021 <!-- src: docs/plan.md -->).

The agents are a LangGraph graph. The ranker and narrator run on Gemini (`gemini-3.8-flash` <!-- src: docs/m2_results.md -->) through Vertex AI; the Skeptic runs on `openai/gpt-5.4-mini` <!-- src: docs/m2_results.md --> through OpenRouter. Every LLM node has a deterministic fallback, every run writes a replayable trace, and no test calls an LLM. FastAPI streams agent events to a single-page Plotly console, deployed on Google Cloud Run.

Claude Code built it on the laptop and, overnight, headless on an Orange Pi. Codex reviewed each milestone.

## Challenges

- **The field note and the numbers disagree at Hepco.** On the Pigeon River near Hepco (USGS 03459500 <!-- src: CLAUDE.md -->), the hydrographer's note reads "Scour control changed". Scour pushes measurements above the curve. The measurements sit 33.1 % <!-- src: docs/m2_results.md --> below it. The Skeptic objects once to a cause that contradicts a control note, then ends in a Disagreement and recommends a level survey.
- **Channel numbers leak.** Discharge equals area times speed, so channel geometry cannot be a predictor. It goes to the Skeptic only, as evidence for the cause.
- **False alarms grow with every look.** On a synthetic null at the Eno River, the size gate cut false alarms from 56 % to 12 % <!-- src: docs/dh_results.md --> at 80 <!-- src: docs/dh_results.md --> post-window visits.
- **Gemini is not deterministic at temperature 0** <!-- src: docs/m2_results.md -->. The first Hepco pick moved between fill and datum change, so we pinned a replay default.

## Accomplishments

- Hepco and Newport come out Stale (24 <!-- src: docs/m2_results.md --> and 30 <!-- src: docs/m2_results.md -->) with the step dated to 2024-12-17 <!-- src: docs/dh_results.md --> and 2024-10-28 <!-- src: docs/dh_results.md -->. The four control gauges come out Trusted.
- On the Mills River the engine finds no step and a slow slide of −0.84 %/yr <!-- src: docs/trend_status.md --> over 164 <!-- src: docs/trend_status.md --> measurements.
- The eval suite passes 11 of 13 <!-- src: docs/eval_report.md --> cases with the fallback in 71 s <!-- src: docs/eval_report.md -->, and it reports its two failures with a diagnosis.

## What we learned

The sign of the residual carries most of the diagnosis, and channel area against water speed carries the rest. At Newport the area grew 25.2 % <!-- src: docs/m2_results.md --> while the water slowed 58.3 % <!-- src: docs/m2_results.md -->, the pattern of fill on the control. A change-point search and a trend test can disagree: on the Eno, a synthetic slope of −1.5 %/yr <!-- src: docs/eval_report.md --> was read as a step.

## What's next

- **Multi-segment rating.** One power law misses the Mills River at high flows. A rating with a break between controls would fit the whole range.
- **Research-grade rating.** A Bayesian rating with uncertainty bands, as in BaRatin, would let rating confidence carry an interval.
- **More gauges.** Every Helene gauge, then a whole state.
- **Rain gauge against radar.** The registry already specifies a module that compares rain gauges with NEXRAD and MRMS radar estimates. Six <!-- src: docs/plan.md --> more modules are specified, from pump curves to meter under-registration.

## Built with

Python, pydantic, NumPy, pandas, SciPy, ruptures, LangGraph, Gemini on Vertex AI, OpenRouter, FastAPI, sse-starlette, Plotly.js, Google Cloud Run, pytest, USGS Water Data API, Claude Code, Codex.
