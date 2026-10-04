"""Shared fixtures. Only synthetic data is used in tests (tests/fixtures and generated panels)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CCRM_DATA_MODE", "deploy")

from src.data import ingestion, sql_runner  # noqa: E402
from src.utils.helpers import load_params  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


@pytest.fixture(scope="session")
def params() -> dict:
    """Project configuration."""
    return load_params()


@pytest.fixture(scope="session")
def credit_fixture() -> pd.DataFrame:
    """Hand-built credit panel with known answers."""
    return pd.read_csv(FIXTURES / "credit_fixture.csv", dtype={"STATUS": str})


def run_sql(credit_path: Path, app_path: Path, params: dict):
    """Run all ten SQL scripts against the given CSVs; returns the DuckDB connection."""
    src = ingestion.RawSource("csv", app_path, credit_path)
    con = ingestion.connect(src)
    ctx = sql_runner.template_context(params)
    sql_runner.run_scripts(con, sql_runner.SCRIPTS, ctx)
    return con


@pytest.fixture(scope="session")
def fixture_db(params):
    """DuckDB with the SQL layer run on the hand-built fixture."""
    return run_sql(FIXTURES / "credit_fixture.csv", FIXTURES / "application_fixture.csv", params)


def synthetic_panel(n_clients: int = 300, seed: int = 7) -> pd.DataFrame:
    """Random synthetic credit panel (leading X, gaps, dormancy, delinquency, pay-off)."""
    rng = np.random.default_rng(seed)
    rows = []
    states = ["0", "1", "2", "3", "4", "5", "C", "X"]
    P = {
        "X": [0.25, 0.01, 0, 0, 0, 0, 0.02, 0.72],
        "0": [0.86, 0.04, 0, 0, 0, 0.002, 0.05, 0.048],
        "1": [0.45, 0.30, 0.15, 0, 0, 0.01, 0.06, 0.03],
        "2": [0.2, 0.15, 0.2, 0.35, 0, 0.02, 0.05, 0.03],
        "3": [0.08, 0.05, 0.07, 0.15, 0.55, 0.05, 0.03, 0.02],
        "4": [0.05, 0, 0.02, 0.01, 0.15, 0.65, 0.1, 0.02],
        "5": [0.02, 0, 0, 0, 0, 0.95, 0.03, 0],
        "C": [0, 0, 0, 0, 0, 0, 1.0, 0],
    }
    for cid in range(n_clients):
        start = int(rng.integers(-60, -1))
        end = int(rng.integers(start + 1, 1))
        s = "X" if rng.random() < 0.4 else "0"
        for mth in range(start, end + 1):
            if rng.random() < 0.03 and mth not in (start, end):
                continue  # gap
            rows.append((100000 + cid, mth, s))
            p = np.array(P[s], dtype=float)
            s = states[int(rng.choice(8, p=p / p.sum()))]
    return pd.DataFrame(rows, columns=["ID", "MONTHS_BALANCE", "STATUS"])


@pytest.fixture(scope="session")
def synthetic_db(params, tmp_path_factory):
    """SQL layer run on a random synthetic panel; returns (connection, credit DataFrame)."""
    d = tmp_path_factory.mktemp("synthetic")
    credit = synthetic_panel()
    credit.to_csv(d / "credit.csv", index=False)
    app = pd.read_csv(FIXTURES / "application_fixture.csv").head(1)
    app.to_csv(d / "application.csv", index=False)
    return run_sql(d / "credit.csv", d / "application.csv", params), credit
