# Deploy status — M5 Cloud Run (C6 part 1)

Status: **green** · 2026-11-07 14:37 EST · branch `m5-deploy` · PR https://github.com/inmang13/driftwatch/pull/15 (base `m3-console`)

## Live
- URL: **https://driftwatch-144765976306.us-east1.run.app**
- Service `driftwatch`, region `us-east1`, project `driftwatch-514015`, revision `driftwatch-00001-2pq`, unauthenticated.
- Env: `LLM=gemini`, `SOURCE=snapshot`, `CORS_ORIGINS=*`, `GOOGLE_CLOUD_PROJECT=driftwatch-514015` (llm.py raises without it).
  `GEMINI_MODEL` / `SKEPTIC_MODEL` unset, so code defaults apply (`gemini-3.8-flash`, `openai/gpt-5.4-mini`).
- Secret: `OPENROUTER_API_KEY` in Secret Manager (version 1, from local .env), mounted `:latest`.
- Runtime SA `144765976306-compute@developer.gserviceaccount.com`: `roles/secretmanager.secretAccessor`, `roles/aiplatform.user`.

## Newport replay trace
- Trace id: **`03455000-20261107T183044853720Z`** (pinned in `traces/replay_defaults.json`)
- Replay: https://driftwatch-144765976306.us-east1.run.app/replay/03455000-20261107T183044853720Z

## Saved traces (already committed, none generated)
- Newport 03455000: `03455000-20261107T183044853720Z`, `03455000-20261107T180338309804Z`
- Swannanoa 03451000: `03451000-20261107T175417762432Z`

## Smoke test (curl, 14:37 EST)
| Check | Result |
|---|---|
| `GET /` | 200, 27.9 KB, title "DriftWatch Console"; `/static/plotly.min.js` 200 |
| `GET /gauges` | 8 sites. Hepco, Newport, Asheville Stale · Mills Watch · Swannanoa, South Toe, Watauga, Eno Trusted |
| `GET /replay/03455000-20261107T183044853720Z?pace=0` | meta 1 · trace 16 · finding 1 |
| `POST /run/03451000` (extra) | live Gemini via the service account, 24 s, `fallbacks_used: 0`, model `vertex:gemini-3.8-flash`, band Trusted |

Not checked: the OpenRouter skeptic on Cloud Run (Swannanoa run didn't call it). Hepco's live run would.

## Notes
- Image: `python:3.13-slim`, package source on `PYTHONPATH=/app` so trace and snapshot paths (computed from `__file__`) resolve under `/app`. `data/snapshot/` and `traces/` baked in.
- `.dockerignore` / `.gcloudignore` also exclude `.env` and `informer-station/`.
- Traces written by live `/run` on Cloud Run land in the container filesystem and vanish on restart; Replay uses the baked traces.
- `curl -X POST` needs `-d ''` (Google front end returns 411 without Content-Length). Browsers' `fetch` are fine.
- CORS is `*` per Grace's deploy prompt; playbook C6 said the Informer origin. Tighten when that origin is known.

## Redeploy
```
gcloud run deploy driftwatch --source . --region us-east1 --allow-unauthenticated --set-secrets OPENROUTER_API_KEY=OPENROUTER_API_KEY:latest --set-env-vars "^@^LLM=gemini@SOURCE=snapshot@CORS_ORIGINS=*@GOOGLE_CLOUD_PROJECT=driftwatch-514015"
```
