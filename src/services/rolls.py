"""Roll rates (business question Q2): matrices with n and intervals, named metrics,
transition trends, absorbing-chain outcomes and the source-literal sensitivity."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.analytics import roll_rates
from src.models.markov import N_TRANSIENT
from src.services import store
from src.services.filters import ALL_BANDS, Filters, apply_dims
from src.utils import constants as C
from src.utils.helpers import load_params

NAMED_LABELS: dict[str, tuple[str, str]] = {
    "cure_30p": ("CURE (30-149 DPD)", C.DEF_CURE),
    f"persistence_{C.B1}": ("PERSISTENCE 30-59", C.DEF_PERSIST),
    f"forward_{C.B0}": ("FORWARD ROLL 1-29", C.DEF_FORWARD),
    "severe_roll_60_89_to_90p": ("SEVERE ROLL 60-89 TO 90+", C.DEF_SEVERE),
    "roll_90p_to_co": ("90+ TO CHARGE-OFF", C.DEF_CO_TRANSITION),
}


def periods() -> list[dict]:
    """Configured calendar windows (on origin month)."""
    return load_params()["periods"]


def _period_bounds(name: str) -> tuple[int, int]:
    for p in periods():
        if p["name"] == name:
            return int(p["start"]), int(p["end"])
    raise KeyError(name)


def _precomputed(slice_type: str, slice_name: str, view: str) -> pd.DataFrame | None:
    rm = store.cube("roll_matrices")
    t = rm[(slice_type == rm.SLICE_TYPE) & (slice_name == rm.SLICE) & (view == rm.VIEW)]
    return None if t.empty else t.copy()


def matrix(period: str, view: str, f: Filters) -> dict[str, Any]:
    """Roll-rate matrix for the selection.

    Returns a dict with ``table`` (FROM_STATE, TO_STATE, n, row_n, p, lo, hi, suppressed,
    warn_small_n), ``interval`` ('bootstrap' or None) and a ``note`` describing the source.
    """
    p = load_params()
    min_n, warn_n = int(p["min_n_row"]), int(p["warn_n_row"])
    key = f.segment_key()
    full = period == "Full window"
    if key:
        if full:
            t = _precomputed(key[0], key[1], view)
            if t is not None:
                return {
                    "table": t,
                    "interval": "bootstrap",
                    "note": "Segment cube (matched clients only); MOB-band and vintage filters do not apply.",
                }
        st = store.cube("segment_transition_cube")
        st = st[(key[0] == st.SEG_TYPE) & (key[1] == st.SEGMENT) & (period == st.PERIOD)]
        counts = roll_rates.counts_from_long(st.fillna({"n": 0}))
        t = roll_rates.matrix_table(counts, None, view, min_n, warn_n)
        sup = st[st.suppressed].set_index(["FROM_STATE", "TO_STATE"]).index
        mask = t.set_index(["FROM_STATE", "TO_STATE"]).index.isin(sup)
        t.loc[mask, ["n", "p"]] = np.nan
        rows = store.cube("segment_transition_rows")
        rows = rows[(key[0] == rows.SEG_TYPE) & (key[1] == rows.SEGMENT) & (period == rows.PERIOD)]
        t["row_n"] = t.FROM_STATE.map(rows.set_index("FROM_STATE").n)
        t["p"] = t.n / t.row_n
        t.loc[t.row_n < min_n, "p"] = np.nan
        t["suppressed"] = t.row_n.isna() | (t.row_n < min_n)
        return {
            "table": t,
            "interval": None,
            "note": "Segment cube by period; cells below 5 are suppressed; no precomputed interval.",
        }
    if not f.dims_active:
        t = _precomputed("period", period, view)
        if t is not None:
            return {"table": t, "interval": "bootstrap", "note": ""}
    if full and f.mob_band != ALL_BANDS and f.vintage_group == "All vintages":
        t = _precomputed("mob_band", f.mob_band, view)
        if t is not None:
            return {"table": t, "interval": "bootstrap", "note": ""}
    lo, hi = _period_bounds(period)
    tc = apply_dims(store.cube("transition_cube"), f)
    tc = tc[(lo <= tc.ORIGIN_MONTH) & (hi >= tc.ORIGIN_MONTH)]
    counts = roll_rates.counts_from_long(tc)
    t = roll_rates.matrix_table(counts, None, view, min_n, warn_n)
    return {"table": t, "interval": None, "note": C.MSG_NO_INTERVAL}


def counts_of(table: pd.DataFrame) -> np.ndarray:
    """(6, 8) counts from a matrix table (suppressed cells count as 0)."""
    return roll_rates.counts_from_long(table.fillna({"n": 0}))


def named_cards(period: str, f: Filters, table: pd.DataFrame) -> list[dict[str, Any]]:
    """Named roll metrics for the current selection with intervals when precomputed."""
    rates = roll_rates.named_metrics(counts_of(table))
    nr = store.cube("named_rolls")
    key = f.segment_key()
    sel = None
    if key and period == "Full window":
        sel = nr[(key[0] == nr.SLICE_TYPE) & (key[1] == nr.SLICE)]
    elif not key and not f.dims_active:
        sel = nr[(nr.SLICE_TYPE == "period") & (period == nr.SLICE)]
    elif (
        not key
        and period == "Full window"
        and f.mob_band != ALL_BANDS
        and f.vintage_group == "All vintages"
    ):
        sel = nr[(nr.SLICE_TYPE == "mob_band") & (f.mob_band == nr.SLICE)]
    cards = []
    for metric, (label, tip) in NAMED_LABELS.items():
        num, den = rates[metric]
        num, den = float(num), float(den)
        value = num / den if den > 0 else np.nan
        ci = None
        if sel is not None and not sel.empty:
            r = sel[metric == sel.METRIC]
            if len(r):
                # Precomputed metric from unsuppressed counts: segment cells below 5 are blanked in
                # the matrix cube, so recomputing from it would understate the numerator.
                value, num, den = float(r.rate.iloc[0]), float(r.num.iloc[0]), float(r.den.iloc[0])
                if np.isfinite(r.lo.iloc[0]):
                    ci = (float(r.lo.iloc[0]), float(r.hi.iloc[0]))
        cards.append(
            {
                "label": label,
                "tooltip": tip,
                "value": value,
                "n": den,
                "events": num if np.isfinite(num) else None,
                "ci": ci,
            }
        )
    return cards


def transition_trend(from_state: str, to_state: str, f: Filters) -> pd.DataFrame:
    """Monthly rate of one transition by origin month with counts (cube dimensions only)."""
    tc = apply_dims(store.cube("transition_cube"), f)
    tc = tc[from_state == tc.FROM_STATE]
    den = tc.groupby("ORIGIN_MONTH").n.sum()
    num = tc[to_state == tc.TO_STATE].groupby("ORIGIN_MONTH").n.sum().reindex(den.index).fillna(0)
    out = pd.DataFrame(
        {"ORIGIN_MONTH": den.index, "n_from": den.values, "n_transition": num.values}
    )
    out["rate"] = np.where(out.n_from > 0, out.n_transition / out.n_from, np.nan)
    return out


def absorbing_table(view: str = "with_dormant") -> pd.DataFrame:
    """P(eventual charge-off / pay-off) and months to resolution by bucket with intervals."""
    a = store.cube("absorbing")
    return a[view == a.VIEW].copy()


def point_of_no_return() -> dict[str, Any]:
    """Point-of-no-return result and its replicate stability."""
    return store.results()["absorbing"]["point_of_no_return"]


def literal_sensitivity() -> tuple[pd.DataFrame, dict[str, Any]]:
    """Source-literal matrix and its summary (demonstrates the degenerate CURRENT row)."""
    return store.cube("literal_sensitivity"), store.results()["literal_sensitivity"]


def origin_states() -> list[str]:
    """Transient origins in display order."""
    return C.MARKOV_ORDER[:N_TRANSIENT]
