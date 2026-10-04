"""02 Roll Rates: where accounts go next and where the point of no return lies (Q2)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import streamlit as st

from app.components import charts, kpi_cards, methodology, tables
from app.components.formatting import PLOTLY_CONFIG, ci, num, pct
from app.components.navigation import banner, page_setup, section
from app.config import supports_plotly_selection
from src.services import rolls
from src.utils import constants as C
from src.utils.helpers import load_params

f = page_setup(
    "Roll Rates",
    "Monthly transition probabilities between delinquency buckets, with n and 95% intervals.",
    "Q2 Where do accounts go next, and where is the point of no return?",
)
st.caption(C.DISCLAIMER_SOURCE)

c1, c2, c3 = st.columns([2, 2, 1])
period = c1.selectbox(
    "Period (origin month window)", [p["name"] for p in rolls.periods()], key="rr_period"
)
view = c2.radio(
    "Destinations",
    ["A: include DORMANT", "B: exclude DORMANT (renormalised)"],
    horizontal=True,
    key="rr_view",
)
show_counts = c3.toggle("Show counts", value=False, key="rr_counts")
vkey = "A" if view.startswith("A") else "B"

res = rolls.matrix(period, vkey, f)
t = res["table"]
if res["note"]:
    banner(res["note"], "info")
origins = [s for s in rolls.origin_states() if not (vkey == "B" and s == C.DORMANT)]
dests = [s for s in C.MARKOV_ORDER if not (vkey == "B" and s == C.DORMANT)]
if t.p.notna().sum() == 0:
    st.info(C.MSG_INSUFFICIENT)
else:
    fig = charts.matrix_heatmap(
        t, origins, dests, show_counts, f"Roll-rate matrix: {period}, view {vkey}"
    )
    if supports_plotly_selection():
        event = st.plotly_chart(
            fig,
            config=PLOTLY_CONFIG,
            theme=None,
            width="stretch",
            on_select="rerun",
            selection_mode="points",
            key="rr_heat",
        )
        pts = event.get("selection", {}).get("points", []) if event else []
        if pts:
            st.session_state["rr_from"] = pts[0]["y"]
            st.session_state["rr_to"] = pts[0]["x"]
    else:
        st.plotly_chart(fig, config=PLOTLY_CONFIG, theme=None, width="stretch")
    sup = t[t.suppressed].FROM_STATE.unique().tolist()
    warn = t[t.warn_small_n].FROM_STATE.unique().tolist()
    notes = []
    if sup:
        notes.append(f"Suppressed rows (n below the minimum): {', '.join(sup)}.")
    if warn:
        notes.append(
            f"Thin rows (n below {load_params()['warn_n_row']}), read with care: {', '.join(warn)}."
        )
    if res["interval"] is None:
        notes.append(C.MSG_NO_INTERVAL + " (hover intervals blank)")
    st.caption(
        " ".join(notes) + " Click a cell, or use the selectors below, to open the detail panel."
    )

section("Transition detail")
d1, d2 = st.columns(2)
st.session_state.setdefault("rr_from", C.B1)
st.session_state.setdefault("rr_to", C.B2)
if st.session_state["rr_from"] not in origins:
    st.session_state["rr_from"] = C.B1
if st.session_state["rr_to"] not in dests:
    st.session_state["rr_to"] = C.B2
fs = d1.selectbox("Origin state", origins, key="rr_from")
ts = d2.selectbox("Destination state", dests, key="rr_to")
cell = t[(fs == t.FROM_STATE) & (ts == t.TO_STATE)]
if not cell.empty:
    r = cell.iloc[0]
    k1, k2, k3 = st.columns(3)
    with k1:
        kpi_cards.value_card(
            f"{fs} TO {ts}",
            pct(r.p, 2) if np.isfinite(r.p) else "&mdash;",
            [ci(r.lo, r.hi, "pct", 2) or C.MSG_NO_INTERVAL],
        )
    with k2:
        kpi_cards.value_card("TRANSITIONS", num(r.n), [f"of {num(r.row_n)} from {fs}"])
    with k3:
        flag = (
            "suppressed" if r.suppressed else ("thin (n < 100)" if r.warn_small_n else "adequate")
        )
        kpi_cards.value_card("ROW SAMPLE", num(r.row_n), [f"Row status: {flag}"])
if not f.segment_active:
    tr = rolls.transition_trend(fs, ts, f)
    if tr.empty or tr.n_from.sum() == 0:
        st.info(C.MSG_INSUFFICIENT)
    else:
        st.plotly_chart(
            charts.line_rate(
                tr,
                "ORIGIN_MONTH",
                "rate",
                f"{fs} to {ts} by origin month",
                "% of origin row",
                C.AXIS_MONTH,
                n_col="n_from",
            ),
            config=PLOTLY_CONFIG,
            theme=None,
            width="stretch",
        )
        st.caption("Monthly rates on thin rows are noisy; hover shows the row n for each month.")
else:
    st.info(
        "Monthly trends are not available for segments (segment cubes are aggregated by period)."
    )

section("Named roll metrics")
items = []
for c in rolls.named_cards(period, f, t):
    items.append(
        {
            "label": c["label"],
            "value": c["value"],
            "n": c["n"],
            "events": c["events"],
            "ci": c["ci"],
            "ci_note": None if c["ci"] else C.MSG_NO_INTERVAL,
            "tooltip": c["tooltip"],
            "d": 2,
        }
    )
kpi_cards.metric_cards(items, per_row=5)

section("Absorbing chain: eventual outcome by bucket")
inc = st.radio(
    "Chain",
    ["DORMANT included (default)", "DORMANT dropped (sensitivity)"],
    horizontal=True,
    key="rr_chain",
)
ab = rolls.absorbing_table(
    "with_dormant" if inc.startswith("DORMANT included") else "dormant_dropped"
)
pnr = rolls.point_of_no_return()[
    "with_dormant" if inc.startswith("DORMANT included") else "dormant_dropped"
]
ab = ab[ab.STATE != C.DORMANT] if not inc.startswith("DORMANT included") else ab
a1, a2 = st.columns([3, 2])
with a1:
    show = ab[ab.STATE.isin([C.B0, C.B1, C.B2, C.B3, C.B4])].copy()
    st.plotly_chart(
        charts.bar_ci(
            show,
            "STATE",
            "p_co",
            "p_co_lo",
            "p_co_hi",
            "P(eventual charge-off) by current bucket",
            "%",
            color="#6B1F2A",
        ),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
with a2:
    if pnr["bucket"]:
        kpi_cards.value_card(
            "POINT OF NO RETURN",
            pnr["bucket"],
            [
                "First bucket where eventual charge-off exceeds eventual pay-off.",
                f"Same bucket in {pnr['replicate_share_same'] * 100:.0f}% of bootstrap replicates.",
            ],
            C.DEF_PNR,
            ["WARNING"] if pnr["replicate_share_same"] < 0.9 else ["PASS"],
        )
    else:
        kpi_cards.value_card(
            "POINT OF NO RETURN", "none", ["No bucket where charge-off is more likely."], C.DEF_PNR
        )
tab = pd.DataFrame(
    {
        "State": ab.STATE,
        "P(eventual charge-off) %": ab.p_co * 100,
        "95% CI": [ci(lo, hi, "pct", 1) for lo, hi in zip(ab.p_co_lo, ab.p_co_hi, strict=True)],
        "P(eventual pay-off) %": ab.p_paid * 100,
        "Expected months to resolution": ab.months,
        "Months 95% CI": [
            ci(lo, hi, "num", 1) for lo, hi in zip(ab.months_lo, ab.months_hi, strict=True)
        ],
    }
)
tables.show(
    tab,
    {
        "P(eventual charge-off) %": tables.pct_col("P(eventual charge-off)"),
        "P(eventual pay-off) %": tables.pct_col("P(eventual pay-off)"),
        "Expected months to resolution": st.column_config.NumberColumn(format="%.1f"),
    },
)
st.caption(
    "Fundamental matrix N = (I - Q)^-1; eventual outcomes B = N R; months to resolution N 1. "
    "Estimated on the full window; intervals from the client-level bootstrap."
)

with st.expander("Sensitivity: source-literal mapping (C = CURRENT, X outside the book)"):
    lm, summ = rolls.literal_sensitivity()
    st.markdown(
        f"Under the literal reading, the CURRENT row stays CURRENT in {pct(summ['current_persistence'], 3)} "
        f"of {num(summ['current_row_n'])} transitions and deteriorates in {pct(summ['current_deterioration'], 4)}. "
        f"CURRENT would be {pct(summ['literal_current_share_m0'])} of non-X accounts at month 0, a share that "
        "can never go bad. This is why C is treated as PAID-OFF (absorbing exit) in every metric."
    )
    piv = lm.pivot_table(index="FROM_STATE", columns="TO_STATE", values="p", aggfunc="first") * 100
    order = ["CURRENT", "1-29", "30-59", "60-89", "90-119", "120-149", "CHARGE-OFF"]
    tables.show(piv.reindex(index=order, columns=order).round(2).reset_index())
methodology.definitions()
