"""04 Delinquency and Cure: how many delinquent accounts cure, how fast, and how many
charge off instead (Q4)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from app.components import charts, kpi_cards, methodology, tables
from app.components.formatting import PLOTLY_CONFIG, ci, pct
from app.components.navigation import page_setup, section
from src.services import cure
from src.utils import constants as C

f = page_setup(
    "Delinquency & Cure",
    "Prevalence of 30+ / 60+ / 90+ and the competing outcomes of 30+ episodes.",
    "Q4 How many delinquent accounts cure, how fast, and how many charge off instead?",
)
st.caption(C.DISCLAIMER_SOURCE)

prev = cure.prevalence()
fig = charts.trend_with_ci(
    prev, "Share of open accounts by bucket (95% bootstrap bands)", "% of open accounts"
)
fig.add_vline(x=f.as_of, line_dash="dot", line_color="#9CA3AF")
st.plotly_chart(fig, config=PLOTLY_CONFIG, theme=None, width="stretch")
st.caption(
    f"30+: {C.DEF_30P} 60+: {C.DEF_60P} 90+: {C.DEF_90P} Charge-off: {C.DEF_CO} "
    "Global segment and MOB filters do not apply to this chart."
)

section("Cure outcomes of 30+ episodes")
k = (
    st.segmented_control(
        "Horizon", [1, 2, 3, 6], default=3, format_func=lambda v: f"{v}M", key="cure_k"
    )
    or 3
)
tab = cure.cif(k)
allr = tab[tab.GRP == "All episodes"].iloc[0]
kpi_cards.metric_cards(
    [
        {
            "label": f"CURED WITHIN {k}M",
            "value": allr.cif_cure,
            "ci": (allr.cif_cure_lo, allr.cif_cure_hi),
            "n": allr.episodes,
            "tooltip": C.DEF_CURE,
        },
        {
            "label": f"CHARGED-OFF WITHIN {k}M",
            "value": allr.cif_co,
            "ci": (allr.cif_co_lo, allr.cif_co_hi),
            "n": allr.episodes,
            "d": 2,
            "tooltip": C.DEF_CO,
        },
        {
            "label": f"STILL 30+ AT {k}M",
            "value": allr.still_30p,
            "ci": (allr.still_30p_lo, allr.still_30p_hi),
            "n": allr.episodes,
            "tooltip": C.DEF_30P,
        },
        {
            "label": "RE-DELINQUENT WITHIN 6M OF CURE",
            "value": cure.redelinquency()["rate"],
            "n": cure.redelinquency()["cured_with_window"],
            "ci_note": "point estimate (complete 6M windows)",
        },
    ],
    per_row=4,
)
st.caption(
    "Primary estimator: discrete-time cumulative incidence with competing risks (cure, charge-off) "
    "and censoring (data end or a dormant month), so recent episodes are not discarded. Episodes whose "
    "first open month is already 30+ are left-censored and excluded."
)

c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(
        charts.outcome_stack(cure.raw_stack(k), f"Raw outcomes within {k}M (censored shown)"),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
with c2:
    grp = st.selectbox("Episode group for curves", cure.groups(), key="cure_grp")
    st.plotly_chart(
        charts.cif_curves(cure.cif_curves(), grp, f"Cumulative incidence: {grp}"),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )

section(f"Primary vs fixed-window estimates at {k}M, by entry bucket")
out = pd.DataFrame(
    {
        "Group": tab.GRP,
        "Episodes": tab.episodes,
        "Cure % (primary)": tab.cif_cure * 100,
        "Cure 95% CI": [
            ci(a, b, "pct", 1) for a, b in zip(tab.cif_cure_lo, tab.cif_cure_hi, strict=True)
        ],
        "Charge-off % (primary)": tab.cif_co * 100,
        "Charge-off 95% CI": [
            ci(a, b, "pct", 2) for a, b in zip(tab.cif_co_lo, tab.cif_co_hi, strict=True)
        ],
        "Eligible (fixed window)": tab.fw_eligible,
        "Cure % (fixed window)": tab.fw_cure * 100,
        "Charge-off % (fixed window)": tab.fw_co * 100,
    }
)
tables.show(out, {c: tables.pct_col(c) for c in out.columns if c.endswith("%") or "% (" in c})
st.caption(
    "Fixed window: only episodes with a complete k-month window inside the data and no censoring "
    "before resolution. 'Entry 60+' episodes are few; read their intervals before any comparison."
)
e60 = tab[tab.GRP == "Entry 60+"].iloc[0]
e30 = tab[tab.GRP == "Entry 30-59"].iloc[0]
st.markdown(
    f"Entry bucket drives outcomes: episodes entering at 30-59 cure within {k}M in {pct(e30.cif_cure)} of cases "
    f"({ci(e30.cif_cure_lo, e30.cif_cure_hi)}), episodes entering at 60+ in {pct(e60.cif_cure)} "
    f"({ci(e60.cif_cure_lo, e60.cif_cure_hi)}; {e60.episodes:,.0f} episodes)."
)
methodology.definitions()
