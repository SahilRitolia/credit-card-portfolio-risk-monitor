"""First-order Markov chain over the eight canonical states.

State order everywhere is :data:`src.utils.constants.MARKOV_ORDER`
(DORMANT, 1-29, 30-59, 60-89, 90-119, 120-149, PAID-OFF, CHARGE-OFF): six transient
states then two absorbing states. Matrices are estimated from transition counts by row
normalisation; absorbing rows are identity. Nothing is hard-coded.

All functions accept a leading batch dimension so that the same code computes the point
estimate (batch of 1) and every bootstrap replicate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils import constants as C

N_STATES = len(C.MARKOV_ORDER)
N_TRANSIENT = len(C.TRANSIENT)
IDX: dict[str, int] = {s: i for i, s in enumerate(C.MARKOV_ORDER)}
DORMANT_IDX = IDX[C.DORMANT]
CO_IDX = IDX[C.CHARGE_OFF]
PAID_IDX = IDX[C.PAID_OFF]


def counts_from_frame(
    df: pd.DataFrame, from_col: str = "FROM_STATE", to_col: str = "TO_STATE", n_col: str = "n"
) -> np.ndarray:
    """Turn a long (from, to, n) table into a (6, 8) transient-origin count array."""
    out = np.zeros((N_TRANSIENT, N_STATES))
    for f, t, n in df[[from_col, to_col, n_col]].itertuples(index=False):
        if f in IDX and IDX[f] < N_TRANSIENT and t in IDX:
            out[IDX[f], IDX[t]] += n
    return out


def estimate(counts: np.ndarray, drop_dormant_dest: bool = False) -> np.ndarray:
    """Row-normalise transient-origin counts into a full 8x8 transition matrix.

    ``counts`` has shape (..., 6, 8). Absorbing rows are identity. A transient row with no
    observations is set to stay in place (and is reported by :func:`empty_rows`).
    With ``drop_dormant_dest`` the DORMANT destination is removed and the row renormalised
    over open and absorbing destinations (matrix view B); the DORMANT row is then kept only
    so shapes stay aligned and is not used by view-B analytics.
    """
    counts = np.asarray(counts, dtype=float)
    batch = counts.shape[:-2]
    c = counts.copy()
    if drop_dormant_dest:
        c[..., DORMANT_IDX] = 0.0
    row = c.sum(axis=-1, keepdims=True)
    P = np.zeros(batch + (N_STATES, N_STATES))
    with np.errstate(invalid="ignore", divide="ignore"):
        P[..., :N_TRANSIENT, :] = np.where(row > 0, c / np.where(row > 0, row, 1.0), 0.0)
    eye = np.eye(N_STATES)
    empty = row[..., 0] == 0
    for i in range(N_TRANSIENT):
        P[..., i, :] = np.where(empty[..., i : i + 1], eye[i], P[..., i, :])
    P[..., N_TRANSIENT:, :] = eye[N_TRANSIENT:]
    return P


def empty_rows(counts: np.ndarray) -> list[str]:
    """Names of transient rows with zero observations (2-D counts only)."""
    return [C.MARKOV_ORDER[i] for i in range(N_TRANSIENT) if counts[i].sum() == 0]


def matrix_power(P: np.ndarray, k: int) -> np.ndarray:
    """Batched integer matrix power (k >= 0)."""
    out = np.broadcast_to(np.eye(P.shape[-1]), P.shape).copy()
    base = P.copy()
    while k > 0:
        if k & 1:
            out = out @ base
        base = base @ base
        k >>= 1
    return out


def forecast(pi: np.ndarray, P: np.ndarray, k: int) -> np.ndarray:
    """Distribution after ``k`` steps: ``pi P^k`` (pi has shape (..., 8))."""
    return np.einsum("...i,...ij->...j", pi, matrix_power(P, k))


def row_sums_ok(P: np.ndarray, tol: float = 1e-9) -> bool:
    """True when every row sums to 1 within ``tol`` and entries lie in [0, 1]."""
    return bool(
        np.all(np.abs(P.sum(axis=-1) - 1.0) <= tol) and np.all(-tol <= P) and np.all(1 + tol >= P)
    )


def to_frame(P: np.ndarray, counts: np.ndarray | None = None) -> pd.DataFrame:
    """Long (FROM_STATE, TO_STATE, p[, n]) table of a single 8x8 matrix."""
    rows = []
    for i, f in enumerate(C.MARKOV_ORDER[:N_TRANSIENT]):
        for j, t in enumerate(C.MARKOV_ORDER):
            r = {"FROM_STATE": f, "TO_STATE": t, "p": float(P[i, j])}
            if counts is not None:
                r["n"] = float(counts[i, j])
            rows.append(r)
    return pd.DataFrame(rows)
