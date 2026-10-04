"""Scenario transform of the base transition matrix (the stress-scenario methodology).

For each transient origin row i, with deterioration multiplier m >= 0 and cure adjustment
c in [-1, 1]:

* worse(i)  = more severe open buckets and CHARGE-OFF: ``p'_w = min(1, m * p_w)``
* benign(i) = less severe open buckets and PAID-OFF:   ``p'_b = max(0, p_b * (1 + c))``
* stay(i)   = own bucket and DORMANT: absorb the residual, split in proportion to their base
  probabilities (all to the own bucket when both are zero)
* if the residual is negative, worse and benign entries are scaled proportionally so the
  row sums to exactly 1 and stay entries are 0.

Severity convention for the DORMANT row: DORMANT ranks with 1-29 (neither is delinquent), so
its worse set is 30-59 .. CHARGE-OFF, its benign set is PAID-OFF, and DORMANT -> 1-29
(reactivation) is left unchanged (docs/decisions.md D-014). Absorbing rows are unchanged.
"""

from __future__ import annotations

import numpy as np

from src.models.markov import IDX, N_STATES, N_TRANSIENT
from src.utils import constants as C

_SEVERITY = {C.DORMANT: 1, C.B0: 1, C.B1: 2, C.B2: 3, C.B3: 4, C.B4: 5}
_OPEN_RANK = {C.B0: 1, C.B1: 2, C.B2: 3, C.B3: 4, C.B4: 5, C.CHARGE_OFF: 6}


def row_sets(state: str) -> tuple[list[int], list[int], list[int], list[int]]:
    """Index lists (worse, benign, stay, unchanged) for a transient origin row."""
    rank = _SEVERITY[state]
    worse = [IDX[s] for s, r in _OPEN_RANK.items() if r > rank]
    benign = [IDX[s] for s, r in _OPEN_RANK.items() if r < rank and s != C.CHARGE_OFF]
    benign.append(IDX[C.PAID_OFF])
    if state == C.DORMANT:
        stay = [IDX[C.DORMANT]]
        benign = [IDX[C.PAID_OFF]]
    else:
        stay = [IDX[state], IDX[C.DORMANT]]
    used = set(worse) | set(benign) | set(stay)
    unchanged = [j for j in range(N_STATES) if j not in used]
    return worse, benign, stay, unchanged


def stress_matrix(P: np.ndarray, m: float | np.ndarray, c: float | np.ndarray) -> np.ndarray:
    """Apply the scenario transform to an 8x8 (optionally batched) matrix.

    ``m`` and ``c`` may be scalars or arrays matching the batch dimensions of ``P``.
    """
    m_arr = np.asarray(m, dtype=float)
    c_arr = np.asarray(c, dtype=float)
    if np.any(m_arr < 0):
        raise ValueError("deterioration multiplier m must be >= 0")
    if np.any(c_arr < -1.0) or np.any(c_arr > 1.0):
        raise ValueError("cure adjustment c must lie in [-1, 1]")
    m = m_arr[..., None] if m_arr.ndim else m_arr
    c = c_arr[..., None] if c_arr.ndim else c_arr
    P = np.asarray(P, dtype=float)
    out = P.copy()
    for i, state in enumerate(C.MARKOV_ORDER[:N_TRANSIENT]):
        worse, benign, stay, unchanged = row_sets(state)
        row = P[..., i, :]
        new = row.copy()
        new[..., worse] = np.minimum(1.0, m * row[..., worse])
        new[..., benign] = np.maximum(0.0, row[..., benign] * (1.0 + c))
        fixed = new[..., unchanged].sum(axis=-1)
        moved = new[..., worse].sum(axis=-1) + new[..., benign].sum(axis=-1)
        residual = 1.0 - fixed - moved
        base_stay = row[..., stay]
        stay_total = base_stay.sum(axis=-1, keepdims=True)
        own_only = np.zeros_like(base_stay)
        own_only[..., 0] = 1.0
        share = np.where(
            stay_total > 0, base_stay / np.where(stay_total > 0, stay_total, 1.0), own_only
        )
        pos = residual >= 0
        new[..., stay] = np.where(pos[..., None], share * np.maximum(residual, 0.0)[..., None], 0.0)
        # Negative residual: scale worse and benign so the row sums to exactly 1.
        scale = np.where(pos, 1.0, (1.0 - fixed) / np.where(moved > 0, moved, 1.0))
        wb = worse + benign
        new[..., wb] = new[..., wb] * scale[..., None]
        out[..., i, :] = new
    return out


def preset_parameters(params: dict) -> dict[str, tuple[float, float]]:
    """Scenario presets (m, c) from configuration, in BASE, MODERATE, SEVERE order."""
    pres = params["stress"]["presets"]
    return {name: (float(v["m"]), float(v["c"])) for name, v in pres.items()}
