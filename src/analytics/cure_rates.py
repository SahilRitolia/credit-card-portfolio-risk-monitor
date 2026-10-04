"""Cure analysis: discrete-time cumulative incidence with competing risks and censoring.

For each episode group, month j = 1..H has n_j episodes at risk and d_cure, d_co, c_j
cured, charged-off and censored episodes. With cause-specific hazards
h_cure = d_cure / n_j and h_co = d_co / n_j and event-free survival
S_j = S_{j-1} (1 - h_cure - h_co):

    CIF_cure(k) = sum_{j<=k} S_{j-1} h_cure_j,   CIF_co(k) = f0 + (1 - f0) sum S_{j-1} h_co_j

where f0 is the share of episodes that enter directly at CHARGE-OFF. Censored episodes leave
the risk set without being counted as failures (Aalen-Johansen style), so recent episodes are
not discarded. CIF_cure + CIF_co + still-30+ = 1 at every k.
"""

from __future__ import annotations

import numpy as np

EVENTS = ("at_risk", "cured", "charged_off", "censored")


def cumulative_incidence(hazards: np.ndarray, immediate: np.ndarray) -> dict[str, np.ndarray]:
    """CIFs from a hazard array.

    ``hazards`` has shape (..., J, 4) with columns (at_risk, cured, charged_off, censored);
    ``immediate`` has shape (..., 2) with (co_at_entry, episodes).
    Returns arrays of shape (..., J): cif_cure, cif_co, still_30p.
    """
    h = np.asarray(hazards, dtype=float)
    imm = np.asarray(immediate, dtype=float)
    n = h[..., 0]
    with np.errstate(invalid="ignore", divide="ignore"):
        hc = np.where(n > 0, h[..., 1] / np.where(n > 0, n, 1.0), 0.0)
        hd = np.where(n > 0, h[..., 2] / np.where(n > 0, n, 1.0), 0.0)
        f0 = np.where(
            imm[..., 1] > 0, imm[..., 0] / np.where(imm[..., 1] > 0, imm[..., 1], 1.0), 0.0
        )
    surv_after = np.cumprod(1.0 - hc - hd, axis=-1)
    surv_before = np.concatenate([np.ones_like(surv_after[..., :1]), surv_after[..., :-1]], axis=-1)
    rest = (1.0 - f0)[..., None]
    cif_cure = rest * np.cumsum(surv_before * hc, axis=-1)
    cif_co = f0[..., None] + rest * np.cumsum(surv_before * hd, axis=-1)
    still = rest * surv_after
    return {"cif_cure": cif_cure, "cif_co": cif_co, "still_30p": still}


def fixed_window(
    eligible: np.ndarray, cured: np.ndarray, charged: np.ndarray
) -> dict[str, np.ndarray]:
    """Secondary estimator: complete-window episodes only."""
    e = np.asarray(eligible, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        cure = np.where(e > 0, np.asarray(cured) / np.where(e > 0, e, 1.0), np.nan)
        co = np.where(e > 0, np.asarray(charged) / np.where(e > 0, e, 1.0), np.nan)
    return {"cure": cure, "co": co, "still": 1.0 - cure - co}
