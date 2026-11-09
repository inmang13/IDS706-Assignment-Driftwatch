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

$(PY):
	$(PYTHON) -m venv .venv

install: $(PY)
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev,agents,api]"

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
