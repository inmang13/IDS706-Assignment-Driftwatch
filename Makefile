# DriftWatch Makefile. Works on Windows (make from PowerShell -> cmd.exe) and Linux (Orange Pi).
# Keep every recipe to plain single commands: no export/source/shell-if, so cmd.exe and sh both run them.

ifeq ($(OS),Windows_NT)
PYTHON ?= python
PY := .venv\Scripts\python.exe
else
PYTHON ?= python3
PY := .venv/bin/python
endif

SOURCE ?= snapshot
SITE ?= 03459500
LLM ?=

.PHONY: install snapshot nldi basemap report run serve test evals demo context
.PHONY: up down dag-test trigger evaluate evaluate-docker logs

$(PY):
	$(PYTHON) -m venv .venv

# ---------------------------------------------------------------- HW: Airflow + warehouse (Docker)
# Start Airflow (:8080, admin/admin), the Postgres warehouse (:5433) and the agent console (:8000).
up:
	docker compose up -d --build

down:
	docker compose down

# Run the whole DAG once, in-process, without the scheduler (fast smoke test; still writes to Postgres)
dag-test:
	docker compose exec airflow-scheduler airflow dags test usgs_rating_pipeline

# Queue a normal run that shows up in the Airflow UI (the DAG also runs daily at 06:00 UTC)
trigger:
	docker compose exec airflow-scheduler airflow dags trigger usgs_rating_pipeline

logs:
	docker compose logs -f airflow-scheduler

# Part 2: run the agent team on all 8 gauges and score it. Locally this reads the snapshot unless
# DRIFTWATCH_SOURCE=warehouse is set; evaluate-docker runs it inside the app container (warehouse).
evaluate:
	$(PY) -m driftwatch.cli evaluate --llm fallback --trace-dir traces/demo

evaluate-docker:
	docker compose exec app python -m driftwatch.cli evaluate --llm fallback --trace-dir traces/demo

install: $(PY)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,agents,api,warehouse]"

# Site list lives in driftwatch/modules/rating_curve/usgs.py (SITES). Refuses unless SOURCE=live (the fetcher enforces it): make snapshot SOURCE=live
snapshot:
	$(PY) -m driftwatch.modules.rating_curve.usgs --source $(SOURCE)

# map layers (basin + main-stem rivers) from USGS NLDI; network, run only on request
nldi:
	$(PY) scripts/fetch_nldi.py

# offline basemap tiles (USGS The National Map topo); network, run only on request
basemap:
	$(PY) scripts/fetch_basemap.py

report:
	$(PY) -m driftwatch.cli report --site $(SITE) --source $(SOURCE)

# LLM empty -> the CLI reads LLM from .env / the shell. make run SITE=03455000 LLM=fallback
run:
	$(PY) -m driftwatch.cli run --site $(SITE) --llm=$(LLM)

# Console at http://localhost:8000/ . LLM for POST /run comes from .env / the shell.
serve:
	$(PY) -m uvicorn driftwatch.api.app:app --host 127.0.0.1 --port 8000

# Web leads for one gauge (Gemini + Google Search), cached in data/context/<site>.json.
# Agent runs only read the cache. make context SITE=03455000
context:
	$(PY) -m driftwatch.agents.context --site $(SITE)

test:
	$(PY) -m pytest -q

# Writes docs/eval_report.md. Fallback always; make evals LLM=gemini adds the Gemini column.
evals:
	$(PY) evals/run_evals.py $(LLM)

# Demo must pass offline: agent runs pinned to the fallback; traces go to traces/demo (gitignored)
# so they never shadow the committed Gemini traces that Replay uses.
demo:
	$(PY) -m driftwatch.cli report --site 03459500 --source snapshot
	$(PY) -m driftwatch.cli report --site 03451000 --source snapshot
	$(PY) -m driftwatch.cli run --site 03459500 --llm fallback --trace-dir traces/demo
	$(PY) -m driftwatch.cli run --site 03451000 --llm fallback --trace-dir traces/demo
