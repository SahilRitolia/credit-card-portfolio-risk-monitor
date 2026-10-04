"""Segment metrics (age band, income quartile) for matched clients, with suppression.

A segment metric is suppressed ('Insufficient observations.') when the segment has fewer than
the configured minimum clients or events. No cross-tabs and no classifier.
"""

from __future__ import annotations

import pandas as pd

from src.utils.constants import MSG_SEGMENT_SUPPRESSED

AGE_ORDER = ["20-29", "30-39", "40-49", "50-59", "60+"]
INCOME_ORDER = ["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"]


def segment_order(seg_type: str) -> list[str]:
    """Display order for a segment type."""
    return AGE_ORDER if seg_type == "age_band" else INCOME_ORDER


def point_rates(seg: pd.DataFrame) -> pd.DataFrame:
    """Add the three rates to ``segment_metrics`` and blank suppressed values."""
    out = seg.copy()
    out["ever60_rate"] = out.ever60_h / out.eligible_h
    out["prev30_rate"] = out.months_30p / out.open_months
    out["cure_rate"] = out.cures / out.trans_30p
    for col, flag in (
        ("ever60_rate", "suppress_ever60"),
        ("prev30_rate", "suppress_prev30"),
        ("cure_rate", "suppress_cure"),
    ):
        out.loc[out[flag], col] = float("nan")
    out["note"] = out.apply(
        lambda r: (
            MSG_SEGMENT_SUPPRESSED
            if (r.suppress_ever60 or r.suppress_prev30 or r.suppress_cure)
            else ""
        ),
        axis=1,
    )
    return out
