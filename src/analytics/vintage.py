"""Vintage curves with the calendar observability rule (cell (v, k) exists iff v + k <= 0).

Quarterly curves aggregate monthly vintages and exist only where every month in the quarter
is observable at that MOB, so a quarterly point never mixes complete and incomplete months.
Curves stop at the last observable MOB and are never extrapolated.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils.helpers import vintage_qtr_label

METRICS: dict[str, str] = {
    "ever_30p": "Ever 30+",
    "ever_60p": "Ever 60+",
    "ever_90p": "Ever 90+",
    "ever_co": "Charge-off",
}


def quarter_months(q: int) -> list[int]:
    """Relative open months that belong to vintage quarter ``q`` (0 = M-60..M-58)."""
    lo = -60 + 3 * q
    return [m for m in range(lo, lo + 3) if m <= 0]


def quarterly_curves(vc: pd.DataFrame) -> pd.DataFrame:
    """Aggregate monthly ``vintage_curves`` to quarters under the observability rule."""
    g = vc.groupby(["VINTAGE_QTR", "MOB"], as_index=False).agg(
        months=("VINTAGE_MONTH", "nunique"),
        n_accounts=("n_accounts", "sum"),
        ever_30p=("ever_30p", "sum"),
        ever_60p=("ever_60p", "sum"),
        ever_90p=("ever_90p", "sum"),
        ever_co=("ever_co", "sum"),
    )
    g["months_in_q"] = g.VINTAGE_QTR.map(lambda q: len(quarter_months(int(q))))
    g = g[g.months == g.months_in_q].drop(columns=["months", "months_in_q"])
    for m in METRICS:
        g[f"{m}_rate"] = g[m] / g.n_accounts
    g["VINTAGE_LABEL"] = g.VINTAGE_QTR.map(lambda q: vintage_qtr_label(int(q)))
    return g.reset_index(drop=True)


def monthly_rates(vc: pd.DataFrame) -> pd.DataFrame:
    """Monthly vintage curves with rates."""
    out = vc.copy()
    for m in METRICS:
        out[f"{m}_rate"] = out[m] / out.n_accounts
    return out


def max_observable_mob(open_month: int) -> int:
    """Largest MOB observable for a vintage opened in ``open_month``."""
    return -int(open_month)


def left_truncation_test(
    mob0_mix: pd.DataFrame, sizes: pd.Series, n_first: int, tol_pp: float
) -> dict:
    """Do the earliest vintages look like pre-existing accounts?

    Compares the MOB-0 state mix (share not in 1-29) of the first ``n_first`` vintage months
    with later vintages, and the size of the first vintage with the median vintage size.
    Fires when the early non-1-29 share exceeds the later share by more than ``tol_pp``
    points, or the first vintage is more than twice the median size (a pile-up).
    """
    mix = mob0_mix.pivot_table(
        index="OPEN_MONTH", columns="STATE", values="n", aggfunc="sum"
    ).fillna(0)
    tot = mix.sum(axis=1)
    non_b0 = 1.0 - mix.get("1-29", pd.Series(0, index=mix.index)) / tot
    first = sorted(mix.index)[:n_first]
    later = [m for m in mix.index if m not in first]
    early_share = float((tot.loc[first] * non_b0.loc[first]).sum() / tot.loc[first].sum())
    later_share = float((tot.loc[later] * non_b0.loc[later]).sum() / tot.loc[later].sum())
    first_size = float(sizes.loc[min(sizes.index)])
    median_size = float(np.median(sizes.values))
    fired = (early_share - later_share) * 100 > tol_pp or first_size > 2 * median_size
    return {
        "first_vintage_month": int(min(sizes.index)),
        "first_vintage_size": first_size,
        "median_vintage_size": median_size,
        "first_vintage_b0_share": float(1 - non_b0.loc[min(mix.index)]),
        "early_non_b0_share": early_share,
        "later_non_b0_share": later_share,
        "fired": bool(fired),
    }
