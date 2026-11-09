# DriftWatch HW — Data Engineering Airflow + agents assignment (copied from the hackathon build 2026-11-09)

This repo is a copy of the DriftWatch hackathon project (AI_HOME/PROJECTS/AIHackathon, commit f672b34)
extended for the course assignment. README.md describes the HW; docs/DRIFTWATCH_README.md is the original.

HW additions (keep these working):
- airflow/dags/usgs_rating_pipeline.py — scheduled DAG; logic lives in driftwatch/pipeline/ (transform, warehouse, analysis).
- docker-compose.yml — Airflow (LocalExecutor) + `warehouse` Postgres (host :5433) + `app` console (:8000).
- Agents: new `data_loader` (reads the warehouse when DRIFTWATCH_SOURCE=warehouse, else the snapshot) and
  `model_evaluator` (driftwatch/modules/rating_curve/evaluate.py) nodes; console.html graph updated to match.
- `python -m driftwatch.cli evaluate` scores the agent run on all 8 gauges → artifacts/agents/evaluation.md.
- tests/test_pipeline.py: pandas cleaning must match pairing.pair_with_counts row for row.

Original hackathon notes below. Build contract: docs/plan.md. Decisions: docs/decision_log.md (append, dated).

## Stack
Python 3.11 · pydantic v2 · numpy/pandas/scipy · ruptures · LangGraph · langchain-google-vertexai (Gemini) · langchain-openai pointed at OpenRouter (skeptic) · FastAPI + sse-starlette · Plotly.js in one static page · pytest · black + ruff.
Package: `driftwatch/` (core, modules/rating_curve, modules/specs, agents, api). Data: `data/snapshot/<site>.json`. Traces: `traces/`.

## Commands
make install · make snapshot (SOURCE=live, only on request) · make report SITE=03459500 · make run SITE=03459500 (agents, writes trace) · make serve (FastAPI :8000, console at /) · make test · make evals · make demo (report + run on 03459500 and 03451000 with LLM=fallback; must pass offline)

## Non-negotiables
- Snapshot is the default source. Live USGS only with SOURCE=live.
- Pair each discharge with the reading_type='MeanGageHeight' stage row on (field_visit_id, time). A visit can hold several discharges.
- Never use channel area/velocity/width as predictors (Q = A·V leakage). Evidence only.
- Keep rating exponent b and offset e fixed from the base fit; drift = sliding a. Report shift in ft and %.
- Exclude measurements rated Poor taken 2024-09-26..28 from the drift test; keep them for plots.
- Residual sign convention: scour → positive; fill → negative; debris/vegetation → negative transient; datum change/rebuild → step of either sign with no channel evidence.
- Every LLM node has a deterministic fallback selected by LLM=fallback. Tests never call an LLM.
- Every agent run writes traces/<site>-<timestamp>.json; the API can replay a trace.
- Trust score is glass-box: the report includes each deduction and its reason.
- Sites: 03459500 03455000 03446000 03451500 03451000 03463300 03479000 02085000. Reference window for the base rating: 2012-01-01 .. 2024-09-25 (Eno: 2015-01-01 .. 2025-07-06).

## Done means
make test green · make demo green offline · Pigeon River near Hepco (03459500) and Newport (03455000) come out Stale with a documented cause · Swannanoa (03451000), South Toe River near Celo (03463300), Eno (02085000) come out Trusted · README run instructions work from a clean clone.