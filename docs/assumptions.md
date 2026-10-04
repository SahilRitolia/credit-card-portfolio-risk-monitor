# Assumptions

| # | Assumption | Why | Where it matters | How to relax |
|---|---|---|---|---|
| A1 | Illustrative assumed EAD - not observed in source data (default 1,000 per open account, configurable) | The data have no balances | Stress page, EL | Load balances and limits; model EAD per account |
| A2 | Illustrative assumed LGD - not observed in source data (default 50%, configurable) | No recoveries in the data | Stress page, EL | Recovery data or a downturn LGD model |
| A3 | Currency symbol is a display choice (default £); the source currency is unknown | Provenance unknown | Every monetary label | Confirm the source |
| A4 | C = PAID-OFF (absorbing exit), X = DORMANT, 0 = 1-29 DPD | Transition evidence in docs/status_semantics.md | Every metric | Source documentation from the data owner |
| A5 | CHARGE-OFF is absorbing; raw departures are anomalies | Charge-off is a terminal accounting event; leaks are rare | Absorbing analytics, EL | Raw-leak sensitivity is reported |
| A6 | First-order, time-homogeneous chain for the base forecast | Standard roll-rate model; tested, not assumed | Forecast page, EL | MOB-conditioned or time-varying matrices (compared in docs/model_validation.md) |
| A7 | Closed-cohort run-off; no new originations | Isolates the behaviour of the existing book | Forecast and EL | Add an origination model |
| A8 | DORMANT accounts carry EAD 0 at origin | No balance that month | EL | Sensitivity toggle includes them |
| A9 | MOB bands early 0-6, middle 7-18, mature 19+ | Keep enough severe transitions per band; tested for homogeneity | MOB slices, MOB model | `config/params.yaml` |
| A10 | Missing target-month records in the backtest are censoring, not a state | Records end without an exit status | Backtest | Observed-subset sensitivity is stored |
| A11 | Flat EAD, no recoveries timing, no discounting, 12-month horizon, not IFRS 9 / CECL | Data limits | EL | Requires exposure and recovery data |
| A12 | Scenario presets (m, c) are illustrative and user-editable | No macro data | Stress | Calibrate to macro scenarios |
