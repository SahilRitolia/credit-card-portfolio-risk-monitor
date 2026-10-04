"""Absorbing-chain analytics: fundamental matrix, eventual outcomes, time to resolution.

With transient block Q and transient-to-absorbing block R of the transition matrix,
``N = (I - Q)^-1`` (expected visits), ``B = N R`` (probability of ending in each absorbing
state) and ``t = N 1`` (expected months to resolution). The point of no return is the first
delinquency bucket, in severity order, where P(eventual charge-off) > P(eventual pay-off).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from src.models.markov import CO_IDX, DORMANT_IDX, N_TRANSIENT, PAID_IDX
from src.utils import constants as C

BUCKET_ORDER: list[str] = [C.B0, C.B1, C.B2, C.B3, C.B4]


@dataclass
class AbsorbingResult:
    """Absorbing analytics for one or many (batched) matrices."""

    states: list[str]  # transient states in the analysed chain
    p_chargeoff: np.ndarray  # (..., n_transient)
    p_paidoff: np.ndarray  # (..., n_transient)
    months_to_resolution: np.ndarray  # (..., n_transient)


def _transient_index(include_dormant: bool) -> list[int]:
    idx = list(range(N_TRANSIENT))
    if not include_dormant:
        idx.remove(DORMANT_IDX)
    return idx


def analyse(P: np.ndarray, include_dormant: bool = True) -> AbsorbingResult:
    """Compute N, B and t for an 8x8 (optionally batched) matrix.

    With ``include_dormant=False`` the DORMANT state is removed: rows of the open buckets are
    renormalised over the remaining transient and absorbing destinations (view B).
    """
    P = np.asarray(P, dtype=float)
    tr = _transient_index(include_dormant)
    ab = [PAID_IDX, CO_IDX]
    keep = tr + ab
    sub = P[..., keep, :][..., :, keep]
    if not include_dormant:
        rs = sub.sum(axis=-1, keepdims=True)
        sub = sub / np.where(rs > 0, rs, 1.0)
    nt = len(tr)
    Q = sub[..., :nt, :nt]
    R = sub[..., :nt, nt:]
    eye = np.broadcast_to(np.eye(nt), Q.shape)
    N = np.linalg.inv(eye - Q)
    B = N @ R
    t = N.sum(axis=-1)
    from src.utils.constants import MARKOV_ORDER

    return AbsorbingResult(
        states=[MARKOV_ORDER[i] for i in tr],
        p_chargeoff=B[..., 1],
        p_paidoff=B[..., 0],
        months_to_resolution=t,
    )


def fundamental_matrix(Q: np.ndarray) -> np.ndarray:
    """``(I - Q)^-1`` for a transient block ``Q``."""
    return np.linalg.inv(np.eye(Q.shape[-1]) - Q)


def point_of_no_return(res: AbsorbingResult) -> str | None:
    """First bucket (severity order) with P(eventual CO) > P(eventual pay-off), else None.

    Works on a single (unbatched) result.
    """
    for b in BUCKET_ORDER:
        i = res.states.index(b)
        if float(res.p_chargeoff[..., i]) > float(res.p_paidoff[..., i]):
            return b
    return None


def point_of_no_return_batch(res: AbsorbingResult) -> list[str | None]:
    """Point of no return for each replicate of a batched result."""
    pco = np.atleast_2d(res.p_chargeoff)
    ppo = np.atleast_2d(res.p_paidoff)
    out: list[str | None] = []
    for r in range(pco.shape[0]):
        hit = None
        for b in BUCKET_ORDER:
            i = res.states.index(b)
            if pco[r, i] > ppo[r, i]:
                hit = b
                break
        out.append(hit)
    return out
