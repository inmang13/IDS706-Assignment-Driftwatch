# DH status: round 3 DONE (2026-11-07, 15:05); round 2 14:22; round 1 14:00

Branch `pi/dh-test`, pushed. It is based on `main` at d30143c (after PR #9). No PR is open; Grace merges.
Built in a separate worktree (`/srv/arx/work/dw-dh`), so the shared checkout at `/srv/arx/work/driftwatch` (on `pi/m1`) was not touched.

| Step | State | Commit |
|---|---|---|
| 1. Two residual series, larger standardized step, `low_flow_concentrated` | done | f5fe1a1 |
| 2. Poor out of the search, quality-weighted median shift sizes | done | 1373437 |
| 3. `suggested_shift_ft` / `suggested_shift_n` (provisional) | done | 2857cdf |
| 4. `reference_mode` fixed / auto, 8 gauges run both ways | done | 3c27159 |
| 5. Tests, `make test`, `make demo`, results doc | done | 971d6c2, 7942b5a |

- `make test`: 113 passed (96 before; 17 new).
- `make demo`: green offline. The fallback verdicts are the same as on `main`.
- Results: docs/dh_results.md. Decisions: docs/decision_log.md, entries "dh 1" to "dh 4".

## Round 2
- Magnitude gate max(10, 1.5 × reference MdAPE), applied to both series; failing change points are merged.
- Auto reference = the most recent stable period ending at least 8 measurements before the latest one. The ≥ 15 measurements over ≥ 2 years floor is kept; that was a judgment call. The holdout is recorded in the Report.
- Eno null rerun at 20 / 40 / 80 visits: 18 / 40 / 56 % without the gate, 2 / 8 / 12 % with it.
- `make test` 117 passed; `make demo` green.
- **Open for Grace:** the auto rule turns Swannanoa, Watauga and Eno Stale, because it falls back to decades-old windows (docs/dh_results.md, Surprise 1). A suggested fix is in that doc but not built.

## Round 3
- Auto = the latest stable period cut off before the newest 8 measurements (the test set). If the latest has fewer than 20 measurements or spans under 2 years, the previous period is the reference and everything after it is tested.
- Expected outcome met. **Mills River disagrees** (Watch 73 fixed vs Trusted 90 auto).
- `make test` 125 passed; `make demo` green.
- Round 2's open item (controls going Stale in auto) is fixed.

## Files touched
`driftwatch/modules/rating_curve/{segmentation,report,pairing}.py`, `driftwatch/core/schemas.py` (fields added only), `tests/test_segmentation.py`, `tests/test_report.py`, `docs/decision_log.md` (appended), `docs/dh_results.md`, `docs/dh_status.md`. Nothing under `driftwatch/agents/` or `driftwatch/api/`.
**Outside the list:** `reports/*.json`, regenerated for all 8 gauges. `make demo` rewrites two of them in any case. They are in their own commit (971d6c2) and can be dropped.

## For Grace
1. ~~Auto mode is one gauging from flipping Newport.~~ Resolved in round 2: the holdout rule never picks the period that runs to the latest gauging. It created the new problem listed under "Round 2" above.
2. Change 2 made the Eno null fire a little more often at long series. The round 2 gate brings it down to 12 % at 80 visits.
3. `reference_mode` can be set only through `build_report(...)`. The CLI and the API were outside this job's files.
4. The pre-existing ruff error in `driftwatch/modules/registry.py` (TRY004) was left alone.
