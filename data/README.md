# Data

## raw/ (git-ignored)

Put the Kaggle files here before running `make build`:

1. Sign in to Kaggle and open https://www.kaggle.com/datasets/rikdifos/credit-card-approval-prediction
2. Download the dataset (a zip containing `application_record.csv` and `credit_record.csv`).
3. Place either the two CSVs or the zip itself in `data/raw/` (or point `CCRM_RAW_DIR` at their folder).

The pipeline reads the zip directly if the CSVs are not extracted. Nothing in `data/raw/` is ever committed.

## processed/

- `cubes/` (committed): aggregated parquet cubes used by the dashboard in deploy mode. No client identifiers; cells with demographic dimensions below 5 accounts are blanked. See `docs/data_dictionary.md`.
- `backtest_results.parquet` (committed): aggregated backtest metrics by origin, horizon and model.
- Anything else written here is git-ignored.

Licence and provenance: `docs/data_licence.md` (UNVERIFIED - human must check).
