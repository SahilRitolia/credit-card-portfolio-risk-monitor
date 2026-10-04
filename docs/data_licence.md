# Data licence and provenance

**Status: UNVERIFIED - human must check.**

| Item | Value |
|---|---|
| Dataset | Credit Card Approval Prediction |
| Kaggle slug | `rikdifos/credit-card-approval-prediction` |
| URL | https://www.kaggle.com/datasets/rikdifos/credit-card-approval-prediction |
| Files used | `application_record.csv`, `credit_record.csv` |
| Date checked | 2026-10-04 |
| Licence text | Not readable from the build environment (Kaggle requires a browser session). A web search returned mirrors of the description but not the licence field. |
| Provenance | The dataset description, as mirrored by third-party catalogues, states that the uploader does not know where the data came from. Institution, country, currency and calendar dates are therefore unknown. |

## Safe default applied in this repository

Because neither the licence nor the provenance could be confirmed, the repository follows **Option A, aggregated cubes only** (`docs/decisions.md`, D-003):

- No raw rows from either CSV are committed. `data/raw/` is git-ignored.
- No client-level table (panel, transitions, episodes) is committed. `data/processed/*` is git-ignored except the whitelisted aggregated cubes in `data/processed/cubes/` and `data/processed/backtest_results.parquet`.
- No committed file contains an `ID` column; `scripts/verify_deliverables.py` and `tests/test_committed_data.py` enforce this.
- Committed cubes that carry a demographic dimension suppress cells with fewer than 5 accounts.

## What the human must do before publishing

1. Open the Kaggle URL above while signed in and read the **License** field and any usage terms.
2. Replace the "Licence text" row above with the exact licence name and the date you read it.
3. If the licence forbids redistribution of derived aggregates, make the repository private and do not deploy the dashboard.

This repository makes no claim of redistribution rights over the dataset. The MIT licence in `LICENSE` covers the code only.
