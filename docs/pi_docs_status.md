---
status: DONE
branch: pi/docs (from origin/main 1f45145)
date: 2026-11-07
---

# pi/docs status

## Result

Docs only; nothing under `driftwatch/`, `evals/`, `traces/` or `data/` changed. Files: `README.md`, `docs/devpost_draft.md` (892 words), `docs/video_script.md` (about 305 spoken words for 2:00), `docs/pitch_script.md` (about 398 spoken words for 3:00), this file, and one appended entry in `docs/decision_log.md`. One commit per file.

## Clean-clone check (thoth, aarch64, Python 3.13, 2026-11-07)

Fresh `git clone` of this branch into an empty directory, new venv, then the README steps exactly:

| Step | Result | Time |
|---|---|---|
| `pip install -e ".[dev,agents,api]" httpx` | exit 0 | about 5 min (20:18 to 20:23 EST) |
| `make test` | 159 passed, exit 0 | 7 min 7 s |
| `make demo` | exit 0, offline, `LLM=fallback`: Hepco Stale 24 (fill, 1 objection, Disagreement against "Scour control changed"); Swannanoa Trusted 94 | 56 s |
| `make serve` | `GET /` 200 (43,410 bytes), `GET /gauges` 8 gauges; server stopped after the check | ready in 9 s |

The README's results table cites this file for these numbers.

## The pitch.md you remembered

It never existed. I searched every local and remote branch, dangling git objects, both stashes and the reflog on thoth and the laptop, the file systems on both machines, and the laptop recycle bin. The plan and playbook only list it as a file for you to draft. Google Drive could not be searched from this session. The closest real source is the "2. Pitch" section of `docs/plan.md`, and `docs/pitch_script.md` is built from it, with the numbers updated to the current reports.

## Bracketed placeholders left

| Placeholder | Where | How to fill it |
|---|---|---|
| [cold-start time, s] | README, under the live URL | Time the first request to the Cloud Run URL after it has been idle. |
| [Gemini eval pass count, of 13] | README eval table, `docs/video_script.md` recording notes, `docs/pitch_script.md` 2:15 beat | `make evals LLM=gemini` on the laptop. |
| [Gemini eval wall time, s] | README eval table | Same run. |
| [Mills high-flow misfit, %] | README, Limits | Share of Mills baseline points in the top third of flows that sit more than 15 % off the curve (`high_flow_misfit` in the API). No doc in the allowed list records Mills's own value. |

Mermaid node labels and `[dev,agents,api]` in square brackets are syntax, not placeholders.

## Notes for Grace

- Hepco has two numbers and the docs keep them apart: the step size is −26 % (−0.33 ft); where the newest 8 measurements sit now is 33.1 % below the curve. The video and pitch use 33.1 % for "where readings sit", as the console does.
- The README's "how AI was used" names the models from `docs/m2_results.md` (Gemini `gemini-3.8-flash` for ranker and narrator, `openai/gpt-5.4-mini` on OpenRouter for the Skeptic). Gemini in VS Code and the Informer app are left out, because nothing in the allowed files shows they shipped.
- The DevPost "Built with" list leaves out Informer for the same reason. Add it back if it is part of the submission.
- Site numbers and dates carry source comments like any other number.
- No PR opened. Open one from the link GitHub prints for `pi/docs`.
