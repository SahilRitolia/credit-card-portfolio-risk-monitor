# Methodology

This document defines every metric and model. Numbers are not repeated here; they are in
`reports/results.json`, `docs/model_validation.md` and the dashboard.

## 1. Time, months on book and the panel

- `MONTHS_BALANCE` is a relative month index: 0 is the extraction month, -60 the earliest. Calendar dates are unknown; charts label the axis "Relative month (0 = extraction month; calendar date unknown)". `MONTH_IDX = MONTHS_BALANCE + 60` is used for plotting only.
- `OPEN_MONTH` is the first month whose status is not X. `MOB = MONTHS_BALANCE - OPEN_MONTH` counts calendar months since then, so dormant months count. `RECORD_MOB` counts from the first record and is kept for the audit.
- Rows before `OPEN_MONTH` (leading X) have MOB NULL and are not part of the opened book. Clients that never have a non-X month stay in the audit only.
- Gaps are detected with `LAG(MONTHS_BALANCE)` and flagged as consecutive, single_gap or multi_gap (`dq_month_gaps`). Gaps are never filled and a missing month is never assumed current.
- Panel grain: ID x MONTHS_BALANCE with state, severity order, flags (IS_OPEN, IS_DORMANT, IS_PAID_OFF, IS_30P, IS_60P, IS_90P, IS_CHARGEOFF), MOB band, vintage month and quarter, and segment attributes for matched clients (`sql/04_account_panel.sql`).

## 2. States and headline definitions

| Raw | State | Class |
|---|---|---|
| 0 | 1-29 DPD | open, transient. Behaves as the performing bucket; headline delinquency is measured at 30+ |
| 1 | 30-59 DPD | open, transient |
| 2 | 60-89 DPD | open, transient |
| 3 | 90-119 DPD | open, transient |
| 4 | 120-149 DPD | open, transient |
| 5 | CHARGE-OFF | absorbing (raw departures flagged in `transition_anomalies`) |
| C | PAID-OFF | absorbing exit (not CURRENT) |
| X | DORMANT | transient, outside the open book |

- **Open account:** status 0-5. Primary denominator for delinquency rates. The alternative denominator (all non-X accounts) is derivable from the stock cube.
- **30+ DPD:** status 1-5 (status 0 excluded). **60+:** 2-5. **90+:** 3-5. **Charge-off:** 5. C and X are never in numerator or denominator.
- **Cure** (from a 30+ bucket): next state 1-29 DPD or PAID-OFF; reported as to 1-29, to paid-off and combined.
- **Forward roll** for bucket b: probability the next state is a more severe open bucket or CHARGE-OFF.
- **Persistence:** probability of staying in the same bucket next month.
- **Named rolls:** 30-59 to 60+; 60-89 to 90+ (severe roll); 90+ to charge-off.

All definitions live once in `src/utils/constants.py` and are imported by SQL comments, services, tooltips and docs.

## 3. Transitions and roll rates

- A transition is (ID, t, STATE_t, STATE_t+1) where both rows exist and the month index differs by exactly 1 (`LEAD` plus a month check). Non-consecutive rows are never paired.
- Origins: DORMANT (post-open) and the five open buckets. Rows leaving PAID-OFF or CHARGE-OFF go to `transition_anomalies`, never into a matrix.
- **View A** (default) keeps DORMANT as a destination. **View B** drops DORMANT destinations and renormalises. Rows sum to 1 (tested to 1e-9).
- Slices: calendar window on origin month, MOB band, vintage quarter, age band, income band. Rows with fewer than 30 transitions are suppressed; fewer than 100 are flagged.
- Entry flows (first activation, returns from DORMANT) and exit flows (open to DORMANT) are reported as flows, not rolls.

## 4. Vintages

- Vintage = OPEN_MONTH (61 monthly cohorts); charts default to quarters.
- Observability: cell (v, k) exists only if v + k <= 0. Denominator = all accounts opened in v. Numerator = accounts whose ever-flag (30+, 60+, 90+, charge-off) is set by MOB k. Curves stop at the last observable MOB and are never extrapolated. A quarterly cell exists only where every month in the quarter is observable.
- Checkpoint comparison at MOB 6/12/18/24: the four most recent observable quarters against the four oldest, with a bootstrap interval for the difference. The verdict is 'higher' or 'lower' only if that interval excludes zero.
- Left-truncation test: MOB-0 state mix and size of the earliest vintages compared with later ones.

## 5. Cure

- Episode: a month with status 1-5 whose previous calendar month exists in the opened book and is not 1-5. Left-censored episodes (first open month already 30+) are flagged and excluded by default.
- For j = 1..6 months after entry, looked up by calendar month: cured (first month in 1-29 or PAID-OFF), charged-off (first month in CHARGE-OFF), censored (missing month or DORMANT before resolution).
- **Primary estimator:** discrete-time cumulative incidence with competing risks. With n_j at risk, cause-specific hazards h_cure = d_cure/n_j and h_co = d_co/n_j and event-free survival S_j = S_{j-1}(1 - h_cure - h_co): CIF_cure(k) = sum S_{j-1} h_cure_j and similarly for charge-off; still-30+ = S_k. Censored episodes leave the risk set without counting as failures. CIF_cure + CIF_co + still-30+ = 1.
- **Secondary estimator:** fixed window, using only episodes whose k-month window is complete and not censored before resolution.
- Breakouts by entry bucket and by previous state; re-delinquency within 6 months after cure.

## 6. Absorbing Markov chain

- Transient T = {DORMANT, 1-29, 30-59, 60-89, 90-119, 120-149}; absorbing A = {PAID-OFF, CHARGE-OFF}. P is the row-normalised count matrix; absorbing rows are identity.
- Forecast: pi_{t+k} = pi_t P^k for the closed cohort of accounts in T at the origin (no new originations).
- With Q (T to T) and R (T to A): N = (I - Q)^-1, B = N R (eventual outcome probabilities), t = N 1 (expected months to resolution). Computed with DORMANT included and, as a sensitivity, with X dropped.
- Point of no return: first bucket in severity order where P(eventual charge-off) > P(eventual pay-off).

## 7. Validation

- Rolling origins with at least 24 months of training transitions; horizons 3, 6, 12 with t0 + h <= 0. Training uses transitions whose destination month is <= t0 (expanding) or the last 24 such months (rolling).
- Baselines: persistence and static portfolio mix. An in-sample oracle (full-window matrix) is an upper bound only.
- Metrics: MAE, RMSE and maximum absolute error across the eight state shares (pp); errors in 30+/60+/90+ share of open accounts; cumulative charge-off error; charge-off count calibration with a bootstrap predictive interval. Skill = 1 - error(model)/error(baseline).
- Stationarity: chi-square homogeneity per origin row between the window halves, total-variation distance, and out-of-time error of a first-half matrix.
- MOB conditioning: per-row chi-square across MOB bands; MOB-conditioned forecasts with band matrices applied in sequence as MOB advances; Dirichlet smoothing tuned on training data; Anderson-Goodman test of second-order dependence for 30+ origins.

## 8. Bootstrap

- Unit = client. A replicate is a multinomial weight vector w over clients (n draws with replacement); counts = w @ S where S holds per-client sufficient statistics. Point estimates use w = 1 through the same code.
- Families: transitions by destination month, by MOB band and by segment; monthly prevalence indicators; backtest cohorts and portfolio mixes; month-0 cohort; vintage checkpoint indicators; cure hazards, fixed-window and raw outcomes; segment counts.
- 95% percentile intervals and bootstrap SE; cells with at least half the replicates exactly zero are flagged as degenerate (report the upper bound). Seeded and reproducible.

## 9. Stress testing and expected loss

- Scenario transform per transient row: worse transitions x m (capped at 1), benign transitions x (1 + c), residual to stay/dormant; proportional rescaling when the residual would be negative. Rows sum to 1 with no negatives; EL is non-decreasing in m and non-increasing in c (tested).
- EL_h = sum_s n_s x EAD x PD_h(s) x LGD with PD_h(s) = (P'^h)[s, CHARGE-OFF]. Open accounts at the origin carry EAD; DORMANT carries 0 unless the sensitivity is on. Accounts already charged off or paid off are excluded.
- Reverse stress: the smallest m at c = 0 that doubles base 12-month EL, by bisection (independent of EAD and LGD), with a bootstrap interval.
- Monetary losses are illustrative and based on assumed exposure and LGD because source data does not contain balances.

## 10. Segmentation

- Matched clients only (non-conflicting application record). Age bands 20-29 .. 60+ from -DAYS_BIRTH/365.25; income quartiles computed on matched clients.
- Metrics: ever-60+ by MOB 12 among accounts old enough, 30+ prevalence over open account-months, one-step cure. Suppressed below 200 clients or 10 events ("Insufficient observations.").
