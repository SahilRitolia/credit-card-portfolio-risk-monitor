"""Vintage performance (business question Q3)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.analytics.vintage import METRICS
from src.services import store


def metric_options() -> dict[str, str]:
    """Metric column -> display label."""
    return METRICS


def quarterly_curves(metric: str, quarters: list[int] | None = None) -> pd.DataFrame:
    """Quarterly curves for ``metric``; truncated at the last observable MOB."""
    q = store.cube("vintage_quarterly")
    out = q[["VINTAGE_QTR", "VINTAGE_LABEL", "MOB", "n_accounts", metric, f"{metric}_rate"]].copy()
    out = out.rename(columns={metric: "events", f"{metric}_rate": "rate"})
    if quarters is not None:
        out = out[out.VINTAGE_QTR.isin(quarters)]
    return out


def heatmap(metric: str, max_mob: int = 36) -> pd.DataFrame:
    """Vintage quarter x MOB matrix of rates; unobservable cells are NaN (blank, not zero)."""
    q = store.cube("vintage_quarterly")
    q = q[max_mob >= q.MOB]
    piv = q.pivot_table(
        index="VINTAGE_LABEL", columns="MOB", values=f"{metric}_rate", aggfunc="first"
    )
    order = q.drop_duplicates("VINTAGE_LABEL").sort_values("VINTAGE_QTR").VINTAGE_LABEL
    return piv.reindex(order).reindex(columns=range(0, max_mob + 1))


def checkpoints(metric: str) -> pd.DataFrame:
    """Rates at MOB 6/12/18/24 by vintage quarter with intervals and n."""
    v = store.cube("vintage_checkpoints")
    return v[metric == v.METRIC].sort_values(["MOB", "VINTAGE_QTR"])


def comparison(metric: str) -> pd.DataFrame:
    """Recent four quarters vs oldest four quarters at each checkpoint with a verdict."""
    c = store.cube("vintage_comparison")
    return c[metric == c.METRIC]


def quarter_options() -> list[tuple[int, str]]:
    """(index, label) of vintage quarters with data."""
    q = store.cube("vintage_quarterly").drop_duplicates("VINTAGE_QTR").sort_values("VINTAGE_QTR")
    return list(zip(q.VINTAGE_QTR.astype(int), q.VINTAGE_LABEL, strict=True))


def left_truncation() -> dict[str, Any]:
    """Left-truncation test result from the data-quality report."""
    return store.dq_report()["left_truncation"]


def first_delinquency() -> pd.DataFrame:
    """MOB of first 30+ by vintage quarter."""
    return store.cube("vintage_first_delinquency")


def max_severity() -> pd.DataFrame:
    """Maximum open bucket reached by vintage quarter (shares)."""
    m = store.cube("vintage_max_severity").copy()
    tot = m.groupby("VINTAGE_QTR").n.transform("sum")
    m["share"] = np.where(tot > 0, m.n / tot, np.nan)
    return m
