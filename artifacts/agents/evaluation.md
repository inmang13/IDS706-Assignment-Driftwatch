# Agent workflow evaluation

- Trust-band accuracy vs hand labels: **8/8 = 100%**
- Rating model, median holdout error across gauges: **4.9%** (log-log baseline 7.7%)
- Share of holdout gaugings within ±10%: **75%** (mean over gauges)

| site | site_name | data_source | band | expected_band | band_correct | trust_score | cause | holdout_mdape_pct | holdout_within_10pct | baseline_mdape_pct | post_mdape_pct | drift_ratio |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 03459500 | PIGEON RIVER NEAR HEPCO, NC | warehouse | Stale | Stale | True | 23.8 | fill | 3.85 | 0.95 | 3.63 | 28.45 | 7.39 |
| 03455000 | FRENCH BROAD RIVER NEAR NEWPORT, TN | warehouse | Stale | Stale | True | 30.0 | fill | 4.35 | 0.812 | 6.51 | 42.34 | 9.73 |
| 03446000 | MILLS RIVER NEAR MILLS RIVER, NC | warehouse | Watch | Watch | True | 73.3 | debris | 5.38 | 0.818 | 8.22 | 10.49 | 1.95 |
| 03451500 | FRENCH BROAD RIVER AT ASHEVILLE, NC | warehouse | Stale | Stale | True | 45.6 | scour | 3.45 | 0.909 | 5.73 | 31.56 | 9.15 |
| 03451000 | SWANNANOA RIVER AT BILTMORE, NC | warehouse | Trusted | Trusted | True | 93.7 |  | 6.52 | 0.696 | 14.97 | 5.31 | 0.81 |
| 03463300 | SOUTH TOE RIVER NEAR CELO, NC | warehouse | Trusted | Trusted | True | 95.0 |  | 2.93 | 0.913 | 7.17 | 5.04 | 1.72 |
| 03479000 | WATAUGA RIVER NEAR SUGAR GROVE, NC | warehouse | Trusted | Trusted | True | 95.0 |  | 10.71 | 0.45 | 20.25 | 3.04 | 0.28 |
| 02085000 | ENO RIVER AT HILLSBOROUGH, NC | warehouse | Trusted | Trusted | True | 90.6 |  | 10.19 | 0.471 | 48.92 | 9.51 | 0.93 |
