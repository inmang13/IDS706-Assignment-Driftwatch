# Pi job #1 — build M1 unattended on thoth (Fri night)

You are building stage M1 of DriftWatch overnight on **thoth**, an Orange Pi Zero 2W in Grace's
room. Nobody will answer questions. When the plan is silent, pick the simplest option, write one
dated line in `docs/decision_log.md`, and keep going.

Read first: `CLAUDE.md`, `docs/plan.md` §3–§4, `docs/agent_playbook.md` §A, `docs/decision_log.md`.
If `docs/m1_status.md` exists you are **resuming** a run that was interrupted: read it and
`git log --oneline -15`, then continue from the first step not marked done. Do not redo green steps.

## The machine you are on (this matters)

- aarch64, 4 cores, **4 GB RAM shared with other services**, SD card storage. Python 3.13 in `.venv/`.
- **Everything is already installed.** Do not `pip install` anything; it needs internet, and the
  internet here is unreliable. If a package seems missing, use what is in `.venv` or write it in
  numpy/scipy, and log the choice.
- **Work fully offline.** Data comes only from `data/snapshot/<site>.json` (`SOURCE=snapshot`). Never
  call the USGS API, never use web search or web fetch. `LLM=fallback`; no LLM calls from code.
- Keep compute small: one site at a time, no parallel pools, no grid searches over thousands of
  settings. Each `make test` run should finish in under 2 minutes.
- Use `.venv/bin/python`, `.venv/bin/pytest`, `.venv/bin/ruff`, `.venv/bin/black`, and `make`.
- You are on branch `pi/m1`. A wrapper script pushes the branch for you after the run; you may also
  run `git push origin pi/m1` after a commit. If the push fails (no network), carry on; never retry
  in a loop. **Never** switch branches, touch `main`, rebase, or force-push.

## Snapshot format (already verified)

`{site, fetched_at, api_base, collections: {"field-measurements": [...], "channel-measurements": [...],
"monitoring-locations": [...]}}`, each item a GeoJSON feature whose `properties` hold the fields.
Field-measurement properties include `field_visit_id`, `time` (ISO, UTC), `parameter_code`
(`00065` stage, `00060` discharge), `reading_type` (stage row to use: `MeanGageHeight`),
`value` (**a string** — cast to float, skip blanks), `unit_of_measure`, `measurement_rated`,
`control_condition`, `approval_status`. Channel-measurement properties include `channel_area`,
`channel_width`, `channel_velocity`, `channel_flow`, `field_visit_id`, `time`.
Station names come from `monitoring-locations` — **use those names in all output**, not the
nicknames in the plan. The decision log already notes 03459500 is Pigeon R near Hepco (not Canton)
and 03463300 is South Toe near Celo. Keep the site IDs as they are; Grace decides the naming.

## Build, in order — commit after each green step

Commit message format: `m1: <what>`. After every commit, update `docs/m1_status.md` with a checklist
of the 8 steps (done / in progress / not started) and one line on what is next, and commit it too.
That file is how a resumed run, and Grace at 8 am, know where you are.

1. **`modules/rating_curve/pairing.py`**: one row per discharge measurement → `Measurement` (use the
   existing schema in `core/schemas.py`; extend it only if needed, keep existing tests green). Stage =
   the `MeanGageHeight` row on the same `field_visit_id` **and** `time`; if there is no exact time
   match, use the nearest `MeanGageHeight` in the same visit within 2 h and log the rule. A visit can
   hold several discharges. Quality weight: Excellent 4, Good 3, Fair 2, Poor 1, else 1.5. Drop rows
   with non-positive stage or discharge. Unit test with a 2-discharge visit fixture.
2. **`rating.py`**: weighted log-space power law Q = a(H−e)^b on the reference window (CLAUDE.md);
   `predict_q(H)`, `predict_h(Q)`, `residual_pct`, `stage_shift_ft` per measurement. Constrain e below
   the minimum reference stage. Use `scipy.optimize` with a bounded 1-D search on e (cheap). Test:
   Eno (02085000) MdAPE inside its reference window < 10 %.
3. **`segmentation.py`**: Darienzo-style recursive segmentation of the residual series with `ruptures`
   (`Pelt(model="l2")`, `min_size=6`), recurse into each segment until no further change point; output
   `stable_periods` and `shifts {time, size_pct, size_ft, direction, n_after, confidence}`. Exclude
   Poor measurements from 2024-09-26..28 from the test. Pick the penalty so Eno (02085000) and
   Swannanoa (03451000) show **no** shift after 2024-09-26 and Newport (03455000) shows one. Try a
   small fixed list of penalties (≤ 15 values), not a search loop. Record the penalty and why in the
   decision log. If no single penalty satisfies all three, choose the best compromise, say so plainly
   in the log, and continue — do not tune forever.
4. **`causes.py`**: the cause catalog (scour, fill/aggradation, debris, vegetation, datum change/gauge
   rebuild, measurement quality, insufficient data), each with expected residual sign and the evidence
   fields an investigator should check. Pure data + a lookup function.
5. **`core/trust.py`**: the glass-box score exactly as plan §4, built with
   `TrustScore.from_deductions`; every `Deduction` carries a plain-English reason with the number in it.
6. **`cli.py`** + `make report SITE=…`: writes `reports/<site>.json` (the `Report` schema) and prints one
   line: station name, band, score, top shift. Replace the `not yet` stub in the Makefile. Also make
   `make demo` run `make report` for 03459500 and 03451000 (the agent part of demo comes later; leave a
   comment). Keep Makefile recipes single plain commands — it must also run on Windows.
7. `make test` green and `make demo` green, offline. Run `.venv/bin/ruff check .` and
   `.venv/bin/black --check .` and fix what they report.
8. **`docs/m1_results.md`**: a table of all 8 sites (station name, band, score, shifts found with dates
   and sizes, median post-2024-09-26 residual %), then a short "surprises" list. Say plainly whether
   03459500's sign disagrees with its "scour" field note (plan §3 flags this). Write it for Grace to
   read in five minutes over coffee: verdict first, no jargon she would have to look up.

## Rules

- Tests are the gate. If a step fails twice, roll back to the last green commit
  (`git checkout -- .` / `git restore`), record what broke in `docs/m1_status.md`, and stop.
- Never edit `docs/plan.md` or `docs/agent_playbook.md`. Append to `docs/decision_log.md` only.
- Never commit `.env`, `.venv`, caches, or anything outside the repo.
- Do not add dependencies to `pyproject.toml`.
- Optional cheap second opinion: `scripts/nip.sh "<question>"` asks a local model (free, may be
  slow or unavailable — ignore it if it errors). Use it only for low-stakes help (wording of
  `m1_results.md`, "anything odd in this table?"). It is **unreliable on hydrology physics** — in
  testing it got the fill/scour residual sign backwards. CLAUDE.md's sign convention is the
  authority; never change code because NIP disagrees.
- Finish by making `docs/m1_status.md` say **DONE** (or **STOPPED: reason**) on its first line.
