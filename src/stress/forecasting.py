"""Closed-cohort run-off forecasts: the accounts in transient states at an origin month,
with no new originations, projected k months ahead with ``pi P^k``."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.markov import N_STATES, N_TRANSIENT, forecast
from src.utils import constants as C


def cohort_vector(counts_by_state: dict[str, float]) -> np.ndarray:
    """Length-6 transient cohort count vector in MARKOV_ORDER."""
    return np.array([float(counts_by_state.get(s, 0.0)) for s in C.TRANSIENT])


def runoff(cohort: np.ndarray, P: np.ndarray, horizons: list[int]) -> pd.DataFrame:
    """Forecast state counts and shares for each horizon (single matrix)."""
    pi0 = np.zeros(N_STATES)
    pi0[:N_TRANSIENT] = cohort
    total = pi0.sum()
    rows = []
    for k in [0, *horizons]:
        v = forecast(pi0, P, k) if k else pi0
        for s, x in zip(C.MARKOV_ORDER, v, strict=True):
            rows.append(
                {
                    "horizon": k,
                    "STATE": s,
                    "count": float(x),
                    "share": float(x / total) if total else np.nan,
                }
            )
    return pd.DataFrame(rows)


def open_share_metrics(dist: np.ndarray) -> dict[str, float]:
    """30+/60+/90+ shares of open accounts (open = 1-29 .. CHARGE-OFF) for one distribution."""
    idx = {s: i for i, s in enumerate(C.MARKOV_ORDER)}
    open_tot = sum(dist[idx[s]] for s in C.OPEN_STATES)
    if open_tot <= 0:
        return {"30+": np.nan, "60+": np.nan, "90+": np.nan}
    return {
        "30+": float(sum(dist[idx[s]] for s in C.DPD30_STATES) / open_tot),
        "60+": float(sum(dist[idx[s]] for s in C.DPD60_STATES) / open_tot),
        "90+": float(sum(dist[idx[s]] for s in C.DPD90_STATES) / open_tot),
    }
