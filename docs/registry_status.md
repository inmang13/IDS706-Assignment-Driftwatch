# Registry status (Pi, 2026-11-07)

**DONE.** Branch `pi/registry`. `make test` green: 53 passed, 6 of them new in `tests/test_registry.py`.

## What was built
1. `driftwatch/modules/specs/*.yaml`: 8 specs. `rating_curve` is live and describes what M1 actually does. The 7 specified modules are `sewer_meter_mass_balance`, `meter_under_registration`, `pump_curve`, `reservoir_stage_storage`, `well_specific_capacity`, `model_calibration` and `rain_gauge_vs_radar`. Each has `title`, `who_cares`, `why_it_drifts`, and the four slots at two sentences each.
2. `driftwatch/modules/registry.py`: `load_registry() -> list[ModuleSpec]` validates every file and returns live first, then by name. Unknown keys, blank fields, a bad status, or a name that does not match its file name all fail loudly.
3. `tests/test_registry.py`: all 8 load, exactly one is live (`rating_curve`, sorted first), every slot is non-empty, plus rejection tests.

## Open for Grace
- Add `pyyaml>=6` to `pyproject.toml` dependencies. It is installed in the venv already, but a clean clone needs it declared.
- If the package is ever installed non-editable (for example on Cloud Run), add `[tool.setuptools.package-data] "driftwatch.modules" = ["specs/*.yaml"]` so the YAML ships with the wheel.
- plan.md §4 still says "7 specified modules". That is still true, but the registry now holds 8 files because the live module has a spec too.

This job only touched `driftwatch/modules/specs/`, `driftwatch/modules/registry.py`, `tests/test_registry.py`, `docs/decision_log.md` (appended) and this file.
