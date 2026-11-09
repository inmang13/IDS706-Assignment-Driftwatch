DONE — Pi job #1 (M1), 2026-11-06. All 8 steps green. Read docs/m1_results.md first.

| # | Step | State |
|---|---|---|
| 1 | pairing.py + test | done |
| 2 | rating.py + Eno MdAPE test | done (Eno MdAPE 8.0 %) |
| 3 | segmentation.py + penalty choice | done (penalty 50; works anywhere in 25–150) |
| 4 | causes.py | done |
| 5 | core/trust.py | done |
| 6 | cli.py + make report / make demo | done |
| 7 | make test + make demo + ruff + black | done (47 passed, ~20 s; demo, ruff, black clean) |
| 8 | docs/m1_results.md | done |

Done-means check: Hepco 03459500 Stale 34 (datum change / rebuild, sign disagrees with its scour
note) · Newport 03455000 Stale 40 (fill) · Swannanoa 94, South Toe 95, Eno 91 all Trusted.

Notes for the morning:
- `git push` from inside the session needed an approval that nobody was there to give, so it was
  not retried. The wrapper script pushes `pi/m1` after the run.
- `make demo` rewrites `reports/03459500.json` and `reports/03451000.json` (only
  `generated_at` changes), so expect those two files in `git status` after running it.
- Open question for Grace: Asheville is 32–36 % off but only "Watch" (56), because the error
  deduction caps at 40. See surprise #1 in m1_results.md.

Next: M2 (agents), per plan §7.
