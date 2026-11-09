---
status: live
stage: m3-design (playbook C10 part 2 + C11 items 1, 2, 4, 5)
date: 2026-11-07
---

# m3-design status

## Needs Grace
- **Open the PR** (gh isn't installed on the laptop):
  https://github.com/inmang13/driftwatch/compare/main...m3-design?expand=1
- **Your stash on main:** the two modified `reports/03451000.json` and `reports/03459500.json` are in
  `git stash` as "pre-m3-design reports". `make demo` rewrites those files on every run, which is why
  they were restored, not committed, on this branch. To get them back: `git checkout main; git stash pop`.
- **Correction:** I first said the `registry.py:59` ruff error was already gone. That was wrong: I had
  checked with the global ruff, and the venv ruff (the project's own) does flag it (TRY004). I
  suppressed it with `# noqa: TRY004` and a reason. I didn't switch to `TypeError`, because every other
  spec check in that file raises `ValueError`, and changing the type would change what callers catch.
- **C11.3 trend sentence:** skipped as you asked. Per your note, it gets wired into the stored reports
  after this branch is merged.
- **Decide:** the education sketches label the y-axis "residual" (the C10 spec's wording). C11.1 would
  say "off curve". Changing it is one word in `sketchSVG`.

## Done (all pushed to `origin/m3-design`)
- Subsection tokens, Archivo + IBM Plex Mono vendored as WOFF2 (`driftwatch/api/static/fonts`, OFL
  texts included), flat 2 px plates, status colour always paired with a word, Plotly recoloured
  (series 1 baseline, series 2 after, series 3 in-between; ink curve; signal Helene line; dashed
  ink-muted change lines; plate-style tooltips). Every chart has a caption naming the gauge and the
  date range, plus a table view.
- Plain language (C11.1). Technical names appear only under "Details and technical names". Model text
  on the card goes through display-only swaps: percents rounded, em dashes become commas, residual →
  reading, the rating → the curve, velocity → water speed, shift → change, reference window → baseline
  period. Open causes read "Lead (unconfirmed)".
- Hepco readouts: "Size of the change in the channel: changed by −26 % in Dec 2024" and "Where the
  newest readings sit now: 33 % below the curve". Every gauge with a change shows both readouts.
- Staggered change labels (C11.2), the Mills high-flow caption (C11.4), and the Education tab built
  from `static/education.json`.
- `make test` passes (155). `make demo` runs through offline. Smoke test
  `scripts/console_smoke.py` passes at desktop and phone width: every tab loads, there are no requests
  to other origins, and there are no page errors. Screenshots are in `docs/images/`.

## Not verified
- Staggering was checked on one real pair only: Helene and the Hepco Dec 2024 change. Mills's two 2016
  lines (the playbook's motivating case) were removed by the shift gate, so that case is no longer in
  the data.
- The more-than-3-changes hover branch never runs on any snapshot gauge.
- The plain-word swaps were dry-traced on the known Hepco, Mills and fallback strings. A new live LLM
  phrasing can still slip through.
- `scripts/console_smoke.py` needs `pip install playwright` (it is not in pyproject) and a running
  server. It is not part of `make test`.

## Judgment calls (also in decision_log)
- Mills caption trigger: ≥ 20 % of baseline points in the top third of flows are > 15 % off the curve,
  AND all of the newest readings (the same 8 the trust score uses) are below that flow cutoff. Only
  Mills qualifies. Eno misses more at high flow (66 %), but one of its newest 8 is a high flow, so the
  caption's "doesn't change the verdict" sentence would be false there.
- The fallback narrator's one em dash became a comma (`agents/fallbacks.py`). The text is otherwise
  unchanged.

## Review (/code-review) leftovers, not fixed
- `high_flow_misfit` is domain logic that lives in `api/app.py`, because `rating_curve/` was
  off-limits this session. Move it there after the freeze.
- The readout box and the agent-graph nodes are 1 px boxes inside 2 px plates. A strict reading of
  "no nested cards" would flag them.
- Small off-scale type: 8 px in the sketch labels and 10 px in the chart annotations.
