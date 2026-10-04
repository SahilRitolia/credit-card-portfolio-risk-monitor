"""Executive overview: KPI cards, trends, state mix, ageing, flows, vintage snapshot and
the computed risk-signal narrative (business question Q1)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.analytics import ageing
from src.services import store
from src.services.filters import Filters, apply_dims
from src.utils import constants as C
from src.utils.helpers import load_params

KPI_DEFS: list[tuple[str, list[str], str]] = [
    ("OPEN ACCOUNTS", C.OPEN_STATES, C.DEF_OPEN),
    ("1-29 DPD", [C.B0], C.DEF_B0),
    ("30+ DPD", C.DPD30_STATES, C.DEF_30P),
    ("60+ DPD", C.DPD60_STATES, C.DEF_60P),
    ("90+ DPD", C.DPD90_STATES, C.DEF_90P),
    ("CHARGE-OFF", [C.CHARGE_OFF], C.DEF_CO),
]
PREV_KEY = {
    "1-29 DPD": "1-29",
    "30+ DPD": "30+",
    "60+ DPD": "60+",
    "90+ DPD": "90+",
    "CHARGE-OFF": "CHARGE-OFF",
}


def state_counts(f: Filters, month: int) -> pd.Series | None:
    """Counts by state at ``month`` under the filters (NaN marks a suppressed cell).

    Returns None when the month is outside the window.
    """
    if month < -60 or month > 0:
        return None
    key = f.segment_key()
    if key:
        s = store.cube("segment_stock_cube")
        s = s[(key[0] == s.SEG_TYPE) & (key[1] == s.SEGMENT) & (month == s.MONTHS_BALANCE)]
        return (
            s.set_index("STATE")
            .n.reindex(C.STATES)
            .fillna(0.0)
            .where(~s.set_index("STATE").suppressed.reindex(C.STATES).fillna(False).astype(bool))
        )
    s = apply_dims(store.cube("stock_cube"), f)
    s = s[month == s.MONTHS_BALANCE]
    return s.groupby("STATE").n.sum().reindex(C.STATES).fillna(0.0)


def _sum(counts: pd.Series, states: list[str]) -> float:
    v = counts.reindex(states)
    return float("nan") if v.isna().any() else float(v.sum())


def kpis(f: Filters) -> list[dict[str, Any]]:
    """Six KPI cards with comparison, changes, n, small-n flag and interval when available."""
    p = load_params()
    small = int(p["min_n_row"])
    cur = state_counts(f, f.as_of)
    prev = state_counts(f, f.as_of - f.compare)
    prev_cube = None if (f.segment_active or f.dims_active) else store.cube("prevalence")
    cards = []
    for label, states, tip in KPI_DEFS:
        n_now = _sum(cur, states) if cur is not None else float("nan")
        open_now = _sum(cur, C.OPEN_STATES) if cur is not None else float("nan")
        n_prev = _sum(prev, states) if prev is not None else float("nan")
        open_prev = _sum(prev, C.OPEN_STATES) if prev is not None else float("nan")
        card: dict[str, Any] = {"label": label, "tooltip": tip, "n": n_now}
        if label == "OPEN ACCOUNTS":
            card.update(
                kind="count", value=n_now, compare=n_prev, change=n_now - n_prev, pp=None, ci=None
            )
        else:
            rate = n_now / open_now if open_now and open_now > 0 else float("nan")
            rprev = n_prev / open_prev if open_prev and open_prev > 0 else float("nan")
            ci = None
            if prev_cube is not None:
                r = prev_cube[
                    (f.as_of == prev_cube.MONTHS_BALANCE) & (PREV_KEY[label] == prev_cube.METRIC)
                ]
                if len(r):
                    ci = (float(r.lo.iloc[0]), float(r.hi.iloc[0]))
            card.update(
                kind="rate",
                value=rate,
                compare=rprev,
                change=n_now - n_prev,
                pp=(rate - rprev) * 100,
                ci=ci,
            )
        card["small_n"] = bool(np.isfinite(n_now) and n_now < small)
        card["missing"] = not np.isfinite(card["value"]) if card["value"] is not None else True
        cards.append(card)
    return cards


def delinquency_trend(f: Filters) -> pd.DataFrame:
    """30+/60+/90+ share of open accounts by month (with intervals when unfiltered)."""
    if not f.segment_active and not f.dims_active:
        d = store.cube("prevalence")
        return d[d.METRIC.isin(["30+", "60+", "90+"])].copy()
    rows = []
    for m in range(-60, 1):
        c = state_counts(
            Filters(as_of=m, mob_band=f.mob_band, vintage_group=f.vintage_group, segment=f.segment),
            m,
        )
        if c is None:
            continue
        o = _sum(c, C.OPEN_STATES)
        for met, states in (
            ("30+", C.DPD30_STATES),
            ("60+", C.DPD60_STATES),
            ("90+", C.DPD90_STATES),
        ):
            num = _sum(c, states)
            rows.append(
                {
                    "MONTHS_BALANCE": m,
                    "METRIC": met,
                    "num": num,
                    "den": o,
                    "rate": num / o if o and o > 0 else np.nan,
                    "lo": np.nan,
                    "hi": np.nan,
                }
            )
    return pd.DataFrame(rows)


def state_distribution(f: Filters) -> pd.DataFrame:
    """All eight states at the as-of month (opened book)."""
    c = state_counts(f, f.as_of)
    if c is None:
        return pd.DataFrame(columns=["STATE", "n"])
    return c.rename("n").rename_axis("STATE").reset_index()


def ageing_by_mob(f: Filters) -> pd.DataFrame | None:
    """Open stock by MOB band x state at the as-of month (None when a segment is selected)."""
    if f.segment_active:
        return None
    return ageing.snapshot(apply_dims(store.cube("stock_cube"), f), f.as_of)


def waterfall(f: Filters) -> pd.DataFrame | None:
    """Open-account flow decomposition into the as-of month (None at the first month)."""
    if f.as_of <= -60:
        return None
    return ageing.open_waterfall(store.cube("flow_table"), f.as_of)


def vintage_snapshot() -> pd.DataFrame:
    """Ever-60+ by MOB 12 by vintage quarter with intervals."""
    v = store.cube("vintage_checkpoints")
    return v[(v.MOB == 12) & (v.METRIC == "ever_60p")].sort_values("VINTAGE_QTR")


def risk_signal(f: Filters) -> dict[str, Any]:
    """Narrative from computed deltas in forward-roll rates (latest 12M vs prior 12M)."""
    rs = store.cube("risk_signal")
    r = rs[f.as_of == rs.AS_OF]
    if r.empty:
        return {"status": "unavailable", "text": C.MSG_UNAVAILABLE, "table": r}
    clear = r[r.clear]
    if clear.empty:
        return {
            "status": "none",
            "text": (
                f"{C.MSG_NO_CLEAR_CHANGE} in forward-roll rates between the 12 months to relative "
                f"month {f.as_of} and the 12 months before (95% client-level bootstrap intervals "
                "include zero, or rows are below the minimum n)."
            ),
            "table": r,
        }
    top = clear.loc[clear["diff"].abs().idxmax()]
    direction = "rose" if top["diff"] > 0 else "fell"
    text = (
        f"Forward roll from {top.BUCKET} DPD {direction} from {top.prior_rate:.2%} to {top.latest_rate:.2%} "
        f"({top['diff'] * 100:+.2f} pp; 95% CI {top.lo * 100:+.2f} to {top.hi * 100:+.2f} pp; "
        f"n = {int(top.latest_n):,} vs {int(top.prior_n):,} transitions) between the 12 months before and "
        f"the 12 months to relative month {f.as_of}."
    )
    return {"status": "signal", "text": text, "table": r}
