"""Stress testing (business question Q6), recomputed live from the transition cube.

The base matrix is re-estimated from the committed transition cube (full window) and the
cohort from the stock cube at relative month 0. Intervals use the precomputed client-level
bootstrap replicate matrices and cohorts (no resampling happens in the app); because EL is
linear in EAD and LGD, any user-chosen EAD/LGD is exact for every replicate.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

from src.analytics.roll_rates import counts_from_long
from src.models import markov
from src.models.markov import N_STATES, N_TRANSIENT
from src.services import store
from src.stress import expected_loss, scenarios
from src.utils import constants as C
from src.utils.helpers import load_params


def config() -> dict[str, Any]:
    """Stress configuration (defaults, presets, horizons)."""
    return load_params()["stress"]


@st.cache_data(show_spinner=False)
def base_matrix() -> np.ndarray:
    """Full-window base matrix re-estimated from the transition cube."""
    return markov.estimate(counts_from_long(store.cube("transition_cube")))


@st.cache_data(show_spinner=False)
def cohort() -> np.ndarray:
    """Transient cohort at relative month 0 from the stock cube (DORMANT + open buckets)."""
    s = store.cube("stock_cube")
    s = s[s.MONTHS_BALANCE == 0].groupby("STATE").n.sum()
    return np.array([float(s.get(x, 0.0)) for x in C.TRANSIENT])


@st.cache_data(show_spinner=False)
def replicates() -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap replicate matrices (B, 8, 8) and cohorts (B, 6)."""
    m = store.cube("stress_bootstrap_matrices")
    B = int(m.rep.max()) + 1
    idx = {s: i for i, s in enumerate(C.MARKOV_ORDER)}
    P = np.zeros((B, N_STATES, N_STATES))
    P[m.rep.to_numpy(), m.FROM_STATE.map(idx).to_numpy(), m.TO_STATE.map(idx).to_numpy()] = (
        m.p.to_numpy()
    )
    c = store.cube("stress_bootstrap_cohort")
    ci = {s: i for i, s in enumerate(C.TRANSIENT)}
    coh = np.zeros((B, N_TRANSIENT))
    coh[c.rep.to_numpy(), c.STATE.map(ci).to_numpy()] = c.n.to_numpy()
    return P, coh


@st.cache_data(show_spinner=False)
def scenario(
    m: float, c: float, ead: float, lgd: float, h: int, include_dormant: bool = False
) -> dict[str, Any]:
    """EL for one scenario with interval, change vs base and contributions by state."""
    level = float(load_params()["bootstrap"]["ci_level"])
    a = (1 - level) / 2
    P, coh = base_matrix(), cohort()
    Pb, cohb = replicates()
    contrib = expected_loss.expected_loss(
        scenarios.stress_matrix(P, m, c), coh, h, ead, lgd, include_dormant
    )
    el = float(contrib.sum())
    base = float(expected_loss.scenario_el(P, coh, h, 1.0, 0.0, ead, lgd, include_dormant))
    elb = expected_loss.scenario_el(Pb, cohb, h, m, c, ead, lgd, include_dormant)
    baseb = expected_loss.scenario_el(Pb, cohb, h, 1.0, 0.0, ead, lgd, include_dormant)
    lo, hi = np.quantile(elb, [a, 1 - a])
    ilo, ihi = np.quantile(elb - baseb, [a, 1 - a])
    with np.errstate(invalid="ignore", divide="ignore"):
        upl_b = np.where(baseb > 0, (elb - baseb) / baseb, np.nan)
    ulo, uhi = np.nanquantile(upl_b, [a, 1 - a])
    stressed = scenarios.stress_matrix(P, m, c)
    return {
        "el": el,
        "el_lo": float(lo),
        "el_hi": float(hi),
        "base": base,
        "incremental": el - base,
        "incremental_lo": float(ilo),
        "incremental_hi": float(ihi),
        "uplift": (el - base) / base if base > 0 else float("nan"),
        "uplift_lo": float(ulo),
        "uplift_hi": float(uhi),
        "contributions": pd.DataFrame({"STATE": C.TRANSIENT, "n": coh, "contribution": contrib}),
        "matrix_ok": markov.row_sums_ok(stressed),
        "stressed_matrix": stressed,
        "expected_chargeoffs": el / (ead * lgd) if ead > 0 and lgd > 0 else float("nan"),
    }


def preset_table(ead: float, lgd: float, include_dormant: bool = False) -> pd.DataFrame:
    """BASE / MODERATE / SEVERE at 6M and 12M under the chosen EAD and LGD."""
    rows = []
    for name, (m, c) in scenarios.preset_parameters(load_params()).items():
        for h in config()["horizons"]:
            r = scenario(m, c, ead, lgd, int(h), include_dormant)
            rows.append(
                {
                    "Scenario": name,
                    "m": m,
                    "c": c,
                    "Horizon (months)": int(h),
                    "EL": r["el"],
                    "EL 95% lo": r["el_lo"],
                    "EL 95% hi": r["el_hi"],
                    "Change vs base": r["incremental"],
                    "Uplift %": r["uplift"] * 100,
                    "Uplift 95% lo": r["uplift_lo"] * 100,
                    "Uplift 95% hi": r["uplift_hi"] * 100,
                }
            )
    return pd.DataFrame(rows)


def reverse_stress() -> dict[str, Any]:
    """Smallest m (c = 0) that doubles base 12M EL, with its bootstrap interval."""
    s = store.results()["stress"]
    return {
        "m": s["reverse_m"],
        "lo": s["reverse_m_lo"],
        "hi": s["reverse_m_hi"],
        "unreached_share": s["reverse_unreached_share"],
    }


def calibration_anchor() -> dict[str, Any]:
    """Model-implied vs observed charge-off count at the latest 12-month backtest origin."""
    cal = store.cube("chargeoff_calibration")
    c12 = cal[cal.horizon == 12]
    r = c12[c12.origin == c12.origin.max()].iloc[0]
    return {k: (v.item() if hasattr(v, "item") else v) for k, v in r.to_dict().items()}


def download_table(
    m: float, c: float, ead: float, lgd: float, h: int, include_dormant: bool
) -> pd.DataFrame:
    """Scenario table for CSV download with every assumption written next to the numbers."""
    cur = config()["currency"]
    t = preset_table(ead, lgd, include_dormant)
    r = scenario(m, c, ead, lgd, h, include_dormant)
    custom = pd.DataFrame(
        [
            {
                "Scenario": "CUSTOM",
                "m": m,
                "c": c,
                "Horizon (months)": h,
                "EL": r["el"],
                "EL 95% lo": r["el_lo"],
                "EL 95% hi": r["el_hi"],
                "Change vs base": r["incremental"],
                "Uplift %": r["uplift"] * 100,
                "Uplift 95% lo": r["uplift_lo"] * 100,
                "Uplift 95% hi": r["uplift_hi"] * 100,
            }
        ]
    )
    out = pd.concat([t, custom], ignore_index=True)
    out["Assumed EAD per open account"] = ead
    out["Assumed LGD"] = lgd
    out["Currency symbol (source currency unknown)"] = cur
    out["DORMANT in EAD base"] = include_dormant
    out["EAD note"] = C.LABEL_EAD
    out["LGD note"] = C.LABEL_LGD
    out["Disclaimer"] = C.DISCLAIMER_EL
    return out
