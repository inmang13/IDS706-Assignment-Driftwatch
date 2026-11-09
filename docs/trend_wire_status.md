# trend-wire status (2026-11-07, branch pi/trend-wire)

The slow-drift trend (`driftwatch/modules/rating_curve/trend.py`) is now part of the Report.
The trust score does not use it.

## What changed

| File | Change |
|---|---|
| `driftwatch/core/schemas.py` | `TrendResult` moved here from trend.py. `Report.trend: TrendResult \| None = None` and `Report.trend_note: str \| None = None` added. |
| `driftwatch/modules/rating_curve/trend.py` | **Outside the allowed edit list, flagged.** The class definition was replaced by `from driftwatch.core.schemas import TrendResult`, re-exported through `__all__`, so `trend.TrendResult` still works. This was needed because trend.py imports schemas, so importing the class from trend.py into schemas.py would be circular. The brief allowed moving the class, and moving it means removing it here. No logic changed. |
| `driftwatch/modules/rating_curve/report.py` | `build_report(..., with_trend: bool = False)`. When True it calls `trend.site_trend(ds, rel, drift)` and sets `trend`. `trend_note` is set (constant `TREND_IN_REFERENCE_NOTE`) only when a trend exists and `trend.window_start.date() < ds.reference_end`. The trust inputs and score are not touched. |
| `driftwatch/cli.py` | `report` passes `with_trend=True`. |
| `reports/*.json` | All 8 regenerated with `make report SITE=<site>`. |
| `tests/test_report.py` | 3 tests (below). |
| `docs/decision_log.md` | One entry appended. |

The API (`driftwatch/api/`) and `console.html` were not touched. The API still calls `build_report` with the default, so it returns `trend: null`.

## Check against main: only the trend fields changed

For each site I loaded `git show origin/main:reports/<site>.json` (origin/main = 64978bf, the base of this branch; the local `main` ref is stale) and the regenerated file. I compared every top-level key except `generated_at`, then compared the band, the score and the top post-reference shift date (`report.top_shift`) on their own.

| Site | Band | Score | Top shift | Other keys changed | Keys added |
|---|---|---|---|---|---|
| 03459500 Hepco | Stale = Stale | 23.8 = 23.8 | 2024-12-17 = 2024-12-17 | none | trend, trend_note |
| 03455000 Newport | Stale = Stale | 30.0 = 30.0 | 2024-10-28 = 2024-10-28 | none | trend, trend_note |
| 03446000 Mills | Watch = Watch | 73.3 = 73.3 | none = none | none | trend, trend_note |
| 03451500 Asheville | Stale = Stale | 45.6 = 45.6 | 2025-07-23 = 2025-07-23 | none | trend, trend_note |
| 03451000 Swannanoa | Trusted = Trusted | 93.7 = 93.7 | none = none | none | trend, trend_note |
| 03463300 South Toe | Trusted = Trusted | 95.0 = 95.0 | none = none | none | trend, trend_note |
| 03479000 Watauga | Trusted = Trusted | 95.0 = 95.0 | none = none | none | trend, trend_note |
| 02085000 Eno | Trusted = Trusted | 90.6 = 90.6 | none = none | none | trend, trend_note |

## Trend values in the stored reports

| Site | Slope %/yr | 95 % CI | p | n | Significant | Window start | Note |
|---|---|---|---|---|---|---|---|
| Hepco | — | | | | None (< 3 yr since shift) | | none |
| Newport | — | | | | None | | none |
| Mills | −0.84 | −1.10..−0.60 | 3.9e-13 | 164 | **yes** ("about 0.8 % lower each year since 2012") | 2012-01-11 | set |
| Asheville | — | | | | None | | none |
| Swannanoa | −0.27 | −0.71..0.09 | 0.053 | 119 | no | 2012-02-13 | set |
| South Toe | +0.17 | −0.19..0.42 | 0.64 | 119 | no | 2012-02-09 | set |
| Watauga | −0.20 | −0.68..0.20 | 0.17 | 104 | no | 2012-01-19 | set |
| Eno | −0.95 | −1.66..−0.10 | 0.012 | 78 | no | 2015-03-04 | set |

Judgment call: the brief ties `trend_note` only to the window start, so the note also appears on the gauges with no significant trend. That covers all 5 gauges that have a trend: with no post-reference shift, the window starts at the reference start. If the note should only go with a significant trend, add `tr.significant and` to the condition in `build_report`.

## Tests (offline, no LLM)

- `test_stored_mills_report_has_a_significant_downward_trend`: reads `reports/03446000.json`. Checks `trend.significant` is True, `"lower"` is in `trend.text`, and the note is set.
- `test_stored_hepco_report_has_no_trend`: reads `reports/03459500.json`. Checks `trend` and `trend_note` are None.
- `test_build_report_skips_the_trend_by_default`: reuses the module's `reports` fixture (5 sites, default arguments). Checks `trend` and `trend_note` are None on every report.

**Runtime on thoth:** the full `make test` suite went from 152 passed in 420.66 s on the branch base to 155 passed in 424.72 s, an increase of **+4.1 s** (limit 60 s). Most of that is `test_cli_writes_report_json_and_prints_station_name`, which now runs the Swannanoa bootstrap (11.8 s for that test). The new tests read JSON and reuse an existing fixture.

## Gates

- `make test`: 155 passed.
- `make demo` (offline, LLM=fallback): green. Hepco Stale 24, Swannanoa Trusted 94, both agent runs finished. The demo rewrites reports/03459500.json and 03451000.json; only `generated_at` changed, so those two edits were reverted rather than committed.
- ruff and black are clean on the changed files. `ruff check driftwatch tests` still reports one TRY004 in `driftwatch/modules/registry.py:59`. That error is already on main and outside this brief.

## Not done / open

- The API and console do not show the trend yet. Another session owns those files.
- `git fetch` needed approval in this unattended session, so the "main" baseline is the `origin/main` ref already on disk (= this branch's base commit).
