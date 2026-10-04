"""Ageing snapshot and month-over-month flows from the stock and flow cubes."""

from __future__ import annotations

import pandas as pd

from src.utils import constants as C


def snapshot(stock: pd.DataFrame, month: int) -> pd.DataFrame:
    """Open-account stock (status 0-5) by state x MOB band for one relative month."""
    s = stock[(month == stock.MONTHS_BALANCE) & stock.STATE.isin(C.OPEN_STATES)]
    return s.groupby(["MOB_BAND", "STATE"], as_index=False)["n"].sum()


def open_waterfall(flows: pd.DataFrame, month: int) -> pd.DataFrame:
    """Decompose the change in open accounts (status 0-5) from month-1 to ``month``.

    Steps: opening open accounts, + newly opened or re-appearing, + returns from DORMANT,
    + other inflows into the open book, - moved to PAID-OFF, - moved to DORMANT,
    - records ended, = closing open accounts.
    """
    f = flows[month == flows.CLOSING_MONTH]
    open_s = set(C.OPEN_STATES)
    from_open = f.FROM_STATE.isin(open_s)
    to_open = f.TO_STATE.isin(open_s)
    opening = float(f.loc[from_open, "n"].sum())
    closing = float(f.loc[to_open, "n"].sum())
    steps = [
        ("Opening (prior month)", opening),
        ("New or re-appearing", float(f.loc[(f.FROM_STATE == "NEW") & to_open, "n"].sum())),
        ("Returned from dormant", float(f.loc[(f.FROM_STATE == C.DORMANT) & to_open, "n"].sum())),
        (
            "Other inflow",
            float(f.loc[(f.FROM_STATE == C.PAID_OFF) & to_open, "n"].sum()),
        ),
        ("To paid-off", -float(f.loc[from_open & (f.TO_STATE == C.PAID_OFF), "n"].sum())),
        ("To dormant", -float(f.loc[from_open & (f.TO_STATE == C.DORMANT), "n"].sum())),
        ("Record ended", -float(f.loc[from_open & (f.TO_STATE == "RECORD ENDS"), "n"].sum())),
    ]
    out = pd.DataFrame(steps, columns=["step", "value"])
    out = pd.concat([out, pd.DataFrame([{"step": "Closing", "value": closing}])], ignore_index=True)
    out["check"] = abs(out.value.iloc[:-1].sum() - closing) < 1e-9
    return out
