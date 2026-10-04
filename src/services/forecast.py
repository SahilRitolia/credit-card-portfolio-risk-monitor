"""Forecast and out-of-time validation (business question Q5)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.services import store
from src.utils import constants as C

MODEL_LABELS: dict[str, str] = {
    "markov": "Markov (expanding)",
    "markov_rolling": "Markov (24M rolling)",
    "mob_conditioned": "MOB-conditioned Markov",
    "markov_observed": "Markov, observed-subset forecast (sensitivity)",
    "persistence": "Baseline: persistence",
    "static_mix": "Baseline: static mix",
    "oracle": "In-sample oracle (upper bound)",
}
METRIC_LABELS: dict[str, str] = {
    "mae_pp": "MAE across states (pp)",
    "rmse_pp": "RMSE across states (pp)",
    "max_abs_pp": "Max abs error (pp)",
    "err_30p_pp": "30+ share of open error (pp)",
    "err_60p_pp": "60+ share of open error (pp)",
    "err_90p_pp": "90+ share of open error (pp)",
    "err_co_pp": "Cumulative charge-off error (pp)",
}


def current_forecast() -> pd.DataFrame:
    """Run-off of the month-0 cohort at 0/3/6/12 months."""
    return store.cube("forecast_current")


def backtest() -> pd.DataFrame:
    """Full backtest table."""
    return store.backtest_results()


def errors(horizon: int, metric: str) -> pd.DataFrame:
    """Error by origin for every model at one horizon."""
    b = backtest()
    return b[(b.horizon == horizon) & (b.metric == metric) & b.model.isin(MODEL_LABELS)]


def skill(horizon: int) -> pd.DataFrame:
    """Skill scores of the expanding Markov model against both baselines."""
    b = backtest()
    return b[(b.horizon == horizon) & b.model.str.startswith("skill_vs_")]


def actual_vs_forecast(origin: int, horizon: int) -> pd.DataFrame:
    """Forecast vs actual state shares for one origin and horizon."""
    b = backtest()
    s = b[(b.origin == origin) & (b.horizon == horizon)]
    fc = s[s.metric.str.startswith("forecast_share:")].assign(
        STATE=lambda d: d.metric.str.split(":").str[1]
    )
    ac = s[s.metric.str.startswith("actual_share:")].assign(
        STATE=lambda d: d.metric.str.split(":").str[1]
    )
    out = pd.DataFrame({"STATE": C.MARKOV_ORDER})
    out = out.merge(
        fc[["STATE", "value"]].rename(columns={"value": "forecast"}), on="STATE", how="left"
    )
    out = out.merge(
        ac[["STATE", "value"]].rename(columns={"value": "actual"}), on="STATE", how="left"
    )
    out["error_pp"] = (out.forecast - out.actual) * 100
    return out


def pairs() -> pd.DataFrame:
    """Valid (origin, horizon) pairs."""
    return backtest()[["origin", "horizon"]].drop_duplicates().sort_values(["horizon", "origin"])


def calibration() -> pd.DataFrame:
    """Predicted vs actual charge-off counts with bootstrap predictive intervals."""
    return store.cube("chargeoff_calibration")


def headline() -> dict[str, Any]:
    """Backtest headline block from results.json."""
    return store.results()["backtest"]


def stationarity() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Half-window homogeneity tests and the out-of-time comparison."""
    return store.cube("stationarity"), store.results()["stationarity"]


def mob_tests() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """MOB homogeneity tests, band probabilities and the history test."""
    return (
        store.cube("mob_homogeneity"),
        store.cube("mob_band_probabilities"),
        store.cube("history_test"),
    )
