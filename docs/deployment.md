# Deployment

## Streamlit Community Cloud (recommended)

1. Push the repository to GitHub.
2. On share.streamlit.io choose **Create app -> Deploy a public app from GitHub**.
3. Settings:
   - Repository: `<your-user>/credit-card-portfolio-risk-monitor`
   - Branch: `main`
   - Main file path: `app/streamlit_app.py`
   - Advanced settings -> Python version: **3.12**
   - Secrets / environment: none required. `CCRM_DATA_MODE` defaults to `deploy`.
4. Community Cloud installs `requirements.txt` (runtime pins only). The app reads `data/processed/cubes/`, `data/processed/backtest_results.parquet` and `reports/*.json`, all committed.

Memory: the largest cube is the bootstrap replicate matrices for the stress page; the app stays well inside Community Cloud limits. No raw data, client-level table or secret is needed.

## Docker

```bash
docker build -t ccrm .
docker run -p 8501:8501 ccrm      # health check: http://localhost:8501/_stcore/health
```

## Local

```bash
make setup && source .venv/bin/activate
make app                           # deploy mode on http://localhost:8501
```

## Updating the deployed numbers

Rebuild locally with the raw files (`make build`), re-render numbers (`make readme-results`), re-capture screenshots (`make screenshots`), run `make verify`, commit the changed cubes and reports, and push. Community Cloud redeploys on push.
