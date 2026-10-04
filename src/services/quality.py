"""Data quality (business question Q7): every check with its rule and status."""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.services import store


def checks() -> pd.DataFrame:
    """All data-quality checks (group, check, value, rule, status, detail)."""
    return pd.DataFrame(store.dq_report()["checks"])


def summary() -> dict[str, int]:
    """Count of PASS / WARNING / FAIL."""
    c = checks()
    return {s: int((c.status == s).sum()) for s in ("PASS", "WARNING", "FAIL")}


def metrics() -> dict[str, float]:
    """Raw audit metrics from sql/02_data_quality.sql."""
    return store.dq_report()["metrics"]


def report() -> dict[str, Any]:
    """The full data-quality report."""
    return store.dq_report()


def pilot_reconciliation() -> pd.DataFrame:
    """Recomputed audit values against the pilot verification targets."""
    return pd.DataFrame(store.dq_report()["pilot_reconciliation"])


def raw_transition_matrix() -> pd.DataFrame:
    """Raw-status transition counts (status-semantics evidence)."""
    df = pd.DataFrame(store.dq_report()["raw_transition_counts"])
    order = ["C", "X", "0", "1", "2", "3", "4", "5"]
    piv = df.pivot_table(
        index="FROM_STATUS", columns="TO_STATUS", values="n", aggfunc="sum"
    ).fillna(0)
    return piv.reindex(index=order, columns=order).fillna(0).astype(int)


def anomalies() -> pd.DataFrame:
    """Transitions leaving an absorbing state (flagged, not fixed)."""
    return pd.DataFrame(store.dq_report()["transition_anomalies"])


def status_mix() -> pd.DataFrame:
    """Row and client counts by raw status."""
    return pd.DataFrame(store.dq_report()["status_counts"])
