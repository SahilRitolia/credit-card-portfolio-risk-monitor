# Data dictionary

## Raw inputs (git-ignored, `data/raw/`)

| File | Column | Type | Meaning |
|---|---|---|---|
| credit_record.csv | ID | integer | Client identifier (join key) |
| | MONTHS_BALANCE | integer | Relative month; 0 = extraction month |
| | STATUS | text | 0, 1-5 (days past due buckets / written off), C (paid off), X (no loan that month) |
| application_record.csv | ID | integer | Client identifier |
| | CODE_GENDER, FLAG_OWN_CAR, FLAG_OWN_REALTY | text | Applicant attributes (not used by any metric) |
| | AMT_INCOME_TOTAL | number | Annual income, currency unknown; used for income quartiles |
| | DAYS_BIRTH | integer | Days before application (negative); age = -DAYS_BIRTH / 365.25 |
| | DAYS_EMPLOYED | integer | Days employed (negative); 365243 is a sentinel set to NULL |
| | NAME_*_TYPE, CNT_*, FLAG_*, OCCUPATION_TYPE | mixed | Other attributes, profiled in the audit only |

## Analytical panel (`panel`, DuckDB only)

| Column | Meaning |
|---|---|
| ID, MONTHS_BALANCE, MONTH_IDX | Grain and plotting index (MONTHS_BALANCE + 60) |
| OPEN_MONTH | First non-X month (= vintage month) |
| MOB / RECORD_MOB | Months since OPEN_MONTH / since first record |
| RAW_STATUS, STATE, STATE_ORDER | Raw status, canonical state, severity rank (0 PAID-OFF .. 7 CHARGE-OFF) |
| IS_OPENED | Row on or after OPEN_MONTH |
| IS_OPEN, IS_DORMANT, IS_PAID_OFF, IS_30P, IS_60P, IS_90P, IS_CHARGEOFF | Headline flags (definitions in docs/methodology.md) |
| MOB_BAND | early 0-6, middle 7-18, mature 19+, or pre-open |
| VINTAGE_MONTH, VINTAGE_QTR | Open month and quarter index (0 = M-60..M-58) |
| HAS_APPLICATION, AGE_BAND, INCOME_BAND | Segment attributes (NULL when unmatched or conflicting) |

## Committed cubes (`data/processed/cubes/*.parquet`, no client identifiers)

| Cube | Grain / columns |
|---|---|
| stock_cube | MONTHS_BALANCE x STATE x MOB_BAND x VINTAGE_QTR, n accounts (opened book) |
| transition_cube | ORIGIN_MONTH x FROM_STATE x TO_STATE x MOB_BAND x VINTAGE_QTR, n transitions |
| flow_table | CLOSING_MONTH x FROM_STATE (or NEW) x TO_STATE (or RECORD ENDS), n |
| entry_exit_flows | MONTH x FLOW (first activation, return from dormant, exit to dormant), n |
| segment_stock_cube | SEG_TYPE x SEGMENT x MONTHS_BALANCE x STATE, n (cells < 5 blanked, `suppressed`) |
| segment_transition_cube / _rows | SEG_TYPE x SEGMENT x PERIOD x FROM x TO (and row totals), n (suppressed < 5) |
| roll_matrices | SLICE_TYPE x SLICE x VIEW x FROM x TO: n, row_n, p, lo, hi, se, degenerate, suppressed, warn_small_n |
| named_rolls | SLICE_TYPE x SLICE x METRIC: num, den, rate, lo, hi |
| literal_sensitivity | Matrix under the source-literal mapping |
| prevalence | MONTHS_BALANCE x METRIC (1-29, 30+, 60+, 90+, CHARGE-OFF): num, den, rate, lo, hi |
| risk_signal | AS_OF x BUCKET: latest and prior forward-roll rates, n, difference, interval, clear flag |
| vintage_monthly / vintage_quarterly | Vintage x MOB: n_accounts, ever_* counts and rates (observable cells only) |
| vintage_checkpoints / vintage_comparison | Rates at MOB 6/12/18/24 with intervals; recent vs oldest quarters with verdict |
| vintage_first_delinquency / vintage_max_severity | MOB of first 30+; maximum bucket reached |
| cure_cif / cure_raw / cure_outcomes_sql | Cumulative incidence and fixed-window estimates; raw outcome stack; SQL outcome counts |
| segments | Segment rates with intervals and suppression flags |
| absorbing | VIEW x STATE: P(eventual CO), P(eventual pay-off), months to resolution, intervals |
| mob_homogeneity, mob_band_probabilities, stationarity, history_test | Validation tests |
| chargeoff_calibration | Origin x horizon: predicted and actual charge-offs, predictive interval |
| forecast_current | Run-off of the month-0 cohort at 0/3/6/12 months |
| stress_presets, stress_contributions | Scenario EL with intervals; EL by origin state |
| stress_bootstrap_matrices / _cohort | Bootstrap replicate matrices and cohorts (aggregated) for live intervals |

`data/processed/backtest_results.parquet`: origin x horizon x model x metric with value, lo, hi, se.
`reports/results.json`: `display` (every number rendered in README/docs) plus detailed sections.
`reports/dq_report.json`: every data-quality metric and check.
