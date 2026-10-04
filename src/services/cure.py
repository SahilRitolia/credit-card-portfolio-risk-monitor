"""Delinquency prevalence and cure (business question Q4)."""

from __future__ import annotations

import pandas as pd

from src.data.feature_engineering import CURE_GROUPS
from src.services import store


def groups() -> list[str]:
    """Episode groups (entry-bucket and previous-state breakouts)."""
    return CURE_GROUPS


def prevalence() -> pd.DataFrame:
    """30+/60+/90+/charge-off share of open accounts by month with intervals."""
    p = store.cube("prevalence")
    return p[p.METRIC.isin(["30+", "60+", "90+", "CHARGE-OFF"])]


def cif(k: int) -> pd.DataFrame:
    """Primary (cumulative incidence) and secondary (fixed-window) estimates at horizon k."""
    c = store.cube("cure_cif")
    return c[k == c.K]


def cif_curves() -> pd.DataFrame:
    """Cumulative incidence at every configured horizon for every group."""
    return store.cube("cure_cif")


def raw_stack(k: int) -> pd.DataFrame:
    """Raw outcome shares within k months (cured / charged-off / still 30+ / censored)."""
    r = store.cube("cure_raw")
    return r[k == r.K]


def redelinquency() -> dict:
    """Re-delinquency within 6 months after a cure."""
    return store.results()["cure_redelinquency"]
