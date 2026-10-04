"""Is first-order Markov enough? MOB-conditioned matrices and homogeneity tests.

Band matrices are estimated by the MOB of the transition's origin month. Sparse band rows
are shrunk toward the pooled row with Dirichlet smoothing of strength ``alpha`` (alpha
pseudo-transitions distributed as the pooled row). ``alpha`` is tuned only on training
data: fit on transitions with destination month <= t0 - v, choose the alpha that maximises
the log-likelihood of transitions in (t0 - v, t0], then refit on all training months.

During a k-step forecast MOB advances: an account with MOB m at the origin takes step j
(j = 1..k) with the matrix of the band of MOB m + j - 1, i.e. the product
P_b(m) P_b(m+1) ... P_b(m+k-1) in transition-origin indexing (the transition-origin convention is the same
sequence in destination indexing as P_b(m+1) ... P_b(m+k)).
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from src.models.markov import N_STATES, N_TRANSIENT, estimate
from src.utils import constants as C


def band_index(mob: np.ndarray | int, bands: list[dict]) -> np.ndarray:
    """Band index (0..len-1) for MOB values using inclusive [lo, hi] bounds."""
    m = np.asarray(mob)
    out = np.full(m.shape, len(bands) - 1)
    for i, b in reversed(list(enumerate(bands))):
        out = np.where((m >= b["lo"]) & (m <= b["hi"]), i, out)
    return out


def smoothed_band_matrices(
    band_counts: np.ndarray, pooled_counts: np.ndarray, alpha: float
) -> np.ndarray:
    """(n_bands, 8, 8) matrices with Dirichlet smoothing toward the pooled row."""
    Pp = estimate(pooled_counts)[:N_TRANSIENT]
    sm = band_counts + alpha * Pp[None, :, :]
    return estimate(sm)


def log_likelihood(P: np.ndarray, counts: np.ndarray) -> float:
    """Sum over cells of n * log p for band matrices P (b,8,8) and counts (b,6,8)."""
    p = P[:, :N_TRANSIENT, :]
    with np.errstate(divide="ignore"):
        lp = np.where(counts > 0, np.log(np.where(p > 0, p, 1e-300)), 0.0)
    return float((counts * lp).sum())


def tune_alpha(
    fit_band: np.ndarray, fit_pooled: np.ndarray, val_band: np.ndarray, grid: list[float]
) -> tuple[float, dict[float, float]]:
    """Choose alpha maximising validation log-likelihood; returns (alpha, scores)."""
    scores = {
        float(a): log_likelihood(smoothed_band_matrices(fit_band, fit_pooled, a), val_band)
        for a in grid
    }
    best = max(scores, key=lambda a: (scores[a], -a))
    return best, scores


def mob_forecast(
    cohort_by_mob: np.ndarray, band_P: np.ndarray, h: int, bands: list[dict]
) -> np.ndarray:
    """Forecast distribution (8,) for a cohort given as (n_mob, 6) counts by origin MOB."""
    dist = np.zeros(N_STATES)
    for m in range(cohort_by_mob.shape[0]):
        v = cohort_by_mob[m]
        if v.sum() == 0:
            continue
        pi = np.zeros(N_STATES)
        pi[:N_TRANSIENT] = v
        for j in range(h):
            pi = pi @ band_P[int(band_index(m + j, bands))]
        dist += pi
    return dist


def homogeneity_tests(band_counts: np.ndarray, band_labels: list[str]) -> list[dict]:
    """Per-origin chi-square test of equal destination distributions across MOB bands."""
    out = []
    for i, f in enumerate(C.MARKOV_ORDER[:N_TRANSIENT]):
        tab = band_counts[:, i, :]
        tab = tab[tab.sum(axis=1) > 0]
        tab = tab[:, tab.sum(axis=0) > 0]
        if tab.shape[0] < 2 or tab.shape[1] < 2:
            out.append(
                {
                    "FROM_STATE": f,
                    "chi2": np.nan,
                    "dof": 0,
                    "p_value": np.nan,
                    "n": float(tab.sum()),
                }
            )
            continue
        chi2, p, dof, _ = stats.chi2_contingency(tab)
        out.append(
            {
                "FROM_STATE": f,
                "chi2": float(chi2),
                "dof": int(dof),
                "p_value": float(p),
                "n": float(tab.sum()),
            }
        )
    return out


def two_sample_tests(counts_a: np.ndarray, counts_b: np.ndarray) -> list[dict]:
    """Per-origin chi-square homogeneity between two count matrices (e.g. two halves)."""
    return homogeneity_tests(np.stack([counts_a, counts_b]), ["a", "b"])


def anderson_goodman(
    triples: dict[tuple[str, str, str], float], current_states: list[str]
) -> list[dict]:
    """Test P(next | current) = P(next | current, previous) for each current state.

    Chi-square on the previous-state x next-state table given the current state.
    """
    out = []
    for cur in current_states:
        prevs = sorted({p for (p, c, _n) in triples if c == cur})
        nexts = sorted({n for (_p, c, n) in triples if c == cur})
        tab = np.array([[triples.get((p, cur, n), 0.0) for n in nexts] for p in prevs])
        if tab.size == 0:
            continue
        tab = tab[tab.sum(axis=1) > 0]
        tab = tab[:, tab.sum(axis=0) > 0]
        if tab.shape[0] < 2 or tab.shape[1] < 2:
            out.append(
                {
                    "CUR_STATE": cur,
                    "chi2": np.nan,
                    "dof": 0,
                    "p_value": np.nan,
                    "n": float(tab.sum()),
                }
            )
            continue
        chi2, p, dof, _ = stats.chi2_contingency(tab)
        out.append(
            {
                "CUR_STATE": cur,
                "chi2": float(chi2),
                "dof": int(dof),
                "p_value": float(p),
                "n": float(tab.sum()),
            }
        )
    return out
