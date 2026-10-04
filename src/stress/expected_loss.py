"""Illustrative expected loss under assumed exposure (EAD) and LGD.

The source data has no balances, so EAD and LGD are assumptions (labelled everywhere):

    EAD base      = accounts open at origin (1-29 .. 120-149); DORMANT carries EAD 0
    PD_h(s)       = (P'^h)[s, CHARGE-OFF]   cumulative probability of charge-off within h months
    EL_h          = sum_s n_s * EAD * PD_h(s) * LGD
    Contribution  = n_s * EAD * PD_h(s) * LGD   per origin state

Accounts already in CHARGE-OFF or PAID-OFF at origin are not in the cohort, so charge-offs
are not double counted.
"""

from __future__ import annotations

import numpy as np

from src.models.markov import CO_IDX, DORMANT_IDX, N_TRANSIENT, matrix_power
from src.stress.scenarios import stress_matrix


def pd_horizon(P: np.ndarray, h: int) -> np.ndarray:
    """Cumulative charge-off probability within ``h`` months from each transient state."""
    return matrix_power(P, h)[..., :N_TRANSIENT, CO_IDX]


def ead_vector(ead: float, include_dormant: bool = False) -> np.ndarray:
    """Per-account exposure by transient origin state."""
    v = np.full(N_TRANSIENT, float(ead))
    if not include_dormant:
        v[DORMANT_IDX] = 0.0
    return v


def expected_loss(
    P: np.ndarray,
    cohort: np.ndarray,
    h: int,
    ead: float,
    lgd: float,
    include_dormant: bool = False,
) -> np.ndarray:
    """EL contribution by origin state, shape (..., 6). Sum the last axis for total EL."""
    pdh = pd_horizon(P, h)
    return np.asarray(cohort, dtype=float) * ead_vector(ead, include_dormant) * pdh * float(lgd)


def scenario_el(
    P: np.ndarray,
    cohort: np.ndarray,
    h: int,
    m: float | np.ndarray,
    c: float | np.ndarray,
    ead: float,
    lgd: float,
    include_dormant: bool = False,
) -> np.ndarray:
    """Total EL under scenario (m, c): shape matches the batch dimensions of ``P``."""
    return expected_loss(stress_matrix(P, m, c), cohort, h, ead, lgd, include_dormant).sum(-1)


def reverse_stress_m(
    P: np.ndarray,
    cohort: np.ndarray,
    h: int,
    target_multiple: float,
    m_upper: float,
    iters: int = 60,
) -> np.ndarray:
    """Smallest m (at c = 0) whose h-month EL is ``target_multiple`` x the base EL.

    Bisection, vectorised over a batch of matrices. EAD and LGD cancel in the ratio.
    Returns NaN where even ``m_upper`` does not reach the target.
    """
    P = np.asarray(P, dtype=float)
    batch = P.shape[:-2]
    base = scenario_el(P, cohort, h, 1.0, 0.0, 1.0, 1.0)
    target = base * target_multiple
    lo = np.ones(batch)
    hi = np.full(batch, float(m_upper))
    reach = _el_at(P, cohort, h, hi) >= target
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        val = _el_at(P, cohort, h, mid)
        ge = val >= target
        hi = np.where(ge, mid, hi)
        lo = np.where(ge, lo, mid)
    return np.where(reach, hi, np.nan)


def _el_at(P: np.ndarray, cohort: np.ndarray, h: int, m: np.ndarray) -> np.ndarray:
    """EL with unit EAD and LGD at a (possibly per-replicate) multiplier ``m``."""
    return scenario_el(P, cohort, h, m, 0.0, 1.0, 1.0)
