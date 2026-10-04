"""Rolling-origin out-of-time backtest of closed-cohort run-off.

Arrays (batched over a leading replicate axis so the bootstrap reuses this code):

* ``trans_dm``  (B, 60, 6, 8): transition counts by destination month (index = dest + 59)
* ``cohort``    (B, 6, 9): cohort at origin t0 by origin state x state at t0+h
                 (8 states + one 'missing' column when the account has no record at t0+h)
* ``portfolio`` (B, 8): all opened accounts observed at t0 by state (static-mix baseline)

Training uses only transitions whose destination month is <= t0 (no leakage). The
expanding model uses every such month; the rolling model the last ``window`` months.
The in-sample oracle uses all transitions including the test period and is an upper bound.
"""

from __future__ import annotations

import numpy as np

from src.models.markov import CO_IDX, N_STATES, N_TRANSIENT, estimate, matrix_power
from src.utils import constants as C

DEST_MONTHS = np.arange(-59, 1)
MISSING = N_STATES  # column index of 'no record at t0+h' in cohort arrays

_I = {s: i for i, s in enumerate(C.MARKOV_ORDER)}
OPEN_IDX = [_I[s] for s in C.OPEN_STATES]
D30_IDX = [_I[s] for s in C.DPD30_STATES]
D60_IDX = [_I[s] for s in C.DPD60_STATES]
D90_IDX = [_I[s] for s in C.DPD90_STATES]


def valid_origins(cfg: dict) -> list[int]:
    """Origins from origin_start to origin_end (step) with >= min_train_months of training."""
    out = []
    for t0 in range(cfg["origin_start"], cfg["origin_end"] + 1, cfg["step"]):
        train_months = t0 - int(DEST_MONTHS[0]) + 1
        if train_months >= cfg["min_train_months"]:
            out.append(t0)
    return out


def training_counts(trans_dm: np.ndarray, t0: int, window: int | None = None) -> np.ndarray:
    """Sum transition counts with destination month in (t0 - window, t0] (all if None)."""
    hi = t0 - int(DEST_MONTHS[0])  # inclusive index of destination month t0
    lo = 0 if window is None else max(0, hi - window + 1)
    return trans_dm[..., lo : hi + 1, :, :].sum(axis=-3)


def _share(x: np.ndarray) -> np.ndarray:
    tot = x.sum(axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, x / np.where(tot > 0, tot, 1.0), np.nan)


def open_ratio(dist: np.ndarray, idx: list[int]) -> np.ndarray:
    """Share of ``idx`` states among open accounts for each distribution."""
    o = dist[..., OPEN_IDX].sum(axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(o > 0, dist[..., idx].sum(axis=-1) / np.where(o > 0, o, 1.0), np.nan)


def errors(fc: np.ndarray, act: np.ndarray) -> dict[str, np.ndarray]:
    """Error metrics between forecast and actual share vectors (percentage points)."""
    d = (fc - act) * 100.0
    out = {
        "mae_pp": np.abs(d).mean(axis=-1),
        "rmse_pp": np.sqrt((d**2).mean(axis=-1)),
        "max_abs_pp": np.abs(d).max(axis=-1),
        "err_30p_pp": (open_ratio(fc, D30_IDX) - open_ratio(act, D30_IDX)) * 100.0,
        "err_60p_pp": (open_ratio(fc, D60_IDX) - open_ratio(act, D60_IDX)) * 100.0,
        "err_90p_pp": (open_ratio(fc, D90_IDX) - open_ratio(act, D90_IDX)) * 100.0,
        "err_co_pp": d[..., CO_IDX],
    }
    for j, s in enumerate(C.MARKOV_ORDER):
        out[f"state_err_pp:{s}"] = d[..., j]
    return out


def evaluate_pair(
    trans_dm: np.ndarray,
    cohort: np.ndarray,
    portfolio: np.ndarray,
    t0: int,
    h: int,
    window: int,
    P_oracle: np.ndarray,
) -> dict[str, dict[str, np.ndarray]]:
    """Forecasts, actuals and error metrics for one (origin, horizon) for every model.

    Primary comparison: forecast for the full origin cohort vs actual shares among the
    cohort members observed at t0+h. Sensitivity ('*_observed'): forecast built from the
    observed members' origin mix only.
    """
    full_mix = cohort.sum(axis=-1)  # (B, 6)
    obs_mix = cohort[..., :MISSING].sum(axis=-1)  # (B, 6) observed at t0+h
    actual_counts = cohort[..., :MISSING].sum(axis=-2)  # (B, 8)
    actual = _share(actual_counts)
    pi_full = np.zeros(full_mix.shape[:-1] + (N_STATES,))
    pi_full[..., :N_TRANSIENT] = full_mix
    pi_obs = np.zeros_like(pi_full)
    pi_obs[..., :N_TRANSIENT] = obs_mix

    models: dict[str, np.ndarray] = {}
    P_exp = estimate(training_counts(trans_dm, t0))
    P_rol = estimate(training_counts(trans_dm, t0, window))
    Pk_exp = matrix_power(P_exp, h)
    models["markov"] = _share(np.einsum("...i,...ij->...j", pi_full, Pk_exp))
    models["markov_observed"] = _share(np.einsum("...i,...ij->...j", pi_obs, Pk_exp))
    models["markov_rolling"] = _share(
        np.einsum("...i,...ij->...j", pi_full, matrix_power(P_rol, h))
    )
    models["oracle"] = _share(np.einsum("...i,...ij->...j", pi_full, matrix_power(P_oracle, h)))
    models["persistence"] = _share(pi_full)
    models["static_mix"] = _share(np.asarray(portfolio, dtype=float))

    out: dict[str, dict[str, np.ndarray]] = {}
    for name, fc in models.items():
        e = errors(fc, actual)
        e["forecast_co_share"] = fc[..., CO_IDX]
        out[name] = e
    n_obs = actual_counts.sum(axis=-1)
    out["_meta"] = {
        "cohort_n": full_mix.sum(axis=-1),
        "observed_n": n_obs,
        "missing_n": cohort[..., MISSING].sum(axis=-1),
        "actual_co": actual_counts[..., CO_IDX],
        "actual_co_share": actual[..., CO_IDX],
        "pred_co_markov": models["markov"][..., CO_IDX] * n_obs,
    }
    for j, s in enumerate(C.MARKOV_ORDER):
        out["_meta"][f"actual_share:{s}"] = actual[..., j]
        out["_meta"][f"forecast_share:{s}"] = models["markov"][..., j]
    return out


def skill(err_model: np.ndarray, err_base: np.ndarray) -> np.ndarray:
    """Skill score 1 - |err_model| / |err_baseline| (NaN when the baseline error is 0)."""
    em, eb = np.abs(err_model), np.abs(err_base)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(eb > 0, 1.0 - em / np.where(eb > 0, eb, 1.0), np.nan)
