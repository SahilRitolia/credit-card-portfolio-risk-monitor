"""01 Executive Overview: who is in the portfolio and how risk is distributed today (Q1)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app.components import charts, kpi_cards, methodology
from app.components.formatting import PLOTLY_CONFIG
from app.components.navigation import banner, page_setup, section
from src.services import overview
from src.utils import constants as C

f = page_setup(
    "Executive Overview",
    "State mix, delinquency trend, ageing and flows for the analysed portfolio sample.",
    "Q1 Who is in the portfolio and how is risk distributed today?",
)
methodology.about()
st.caption(C.DISCLAIMER_SOURCE)

if f.segment_active and f.dims_active:
    banner(
        "Segment cubes are not cross-classified by MOB band or vintage; those filters are ignored "
        "while a segment is selected.",
        "info",
    )

cards = overview.kpis(f)
kpi_cards.portfolio_kpis(cards, f"vs M{f.as_of - f.compare}", C.MSG_INSUFFICIENT)
st.caption(
    "Rates are shares of open accounts (status 0-5). CHARGE-OFF is the stock of accounts in status 5 that "
    "month (accounts can stay in status 5 for several months), not the number of new charge-offs. "
    "SMALL n marks counts below the minimum row size."
)

sig = overview.risk_signal(f)
st.markdown(
    f'<div class="ccrm-signal"><b>RISK SIGNAL</b>{sig["text"]}</div>', unsafe_allow_html=True
)

c1, c2 = st.columns([3, 2])
with c1:
    trend = overview.delinquency_trend(f)
    if trend.empty or trend.rate.notna().sum() == 0:
        st.info(C.MSG_INSUFFICIENT)
    else:
        fig = charts.trend_with_ci(
            trend, "Delinquency share of open accounts", "% of open accounts"
        )
        fig.add_vline(x=f.as_of, line_dash="dot", line_color="#9CA3AF")
        st.plotly_chart(fig, config=PLOTLY_CONFIG, theme=None, width="stretch")
        st.caption(
            "Shaded bands: 95% client-level bootstrap intervals (unfiltered view only). "
            f"30+: {C.DEF_30P}"
        )
with c2:
    dist = overview.state_distribution(f)
    if dist.empty or dist.n.sum() == 0:
        st.info(C.MSG_INSUFFICIENT)
    else:
        st.plotly_chart(
            charts.state_bars(dist, f"Opened book by state, M{f.as_of}"),
            config=PLOTLY_CONFIG,
            theme=None,
            width="stretch",
        )

c3, c4 = st.columns(2)
with c3:
    ag = overview.ageing_by_mob(f)
    if ag is None:
        st.info(
            "Ageing by MOB band is not available for a segment (segment cubes carry no MOB dimension)."
        )
    elif ag.empty:
        st.info(C.MSG_INSUFFICIENT)
    else:
        st.plotly_chart(
            charts.stacked_by_band(ag, f"Open accounts by MOB band, M{f.as_of}"),
            config=PLOTLY_CONFIG,
            theme=None,
            width="stretch",
        )
with c4:
    wf = overview.waterfall(f)
    if wf is None:
        st.info(C.MSG_UNAVAILABLE)
    else:
        st.plotly_chart(
            charts.waterfall(
                wf, f"Open-account bridge M{f.as_of - 1} to M{f.as_of} (all accounts)"
            ),
            config=PLOTLY_CONFIG,
            theme=None,
            width="stretch",
        )
        st.caption("Flows are shown for the whole opened book; open = status 0-5.")

section("Vintage risk snapshot")
vs = overview.vintage_snapshot()
if vs.empty:
    st.info(C.MSG_INSUFFICIENT)
else:
    st.plotly_chart(
        charts.bar_ci(
            vs,
            "VINTAGE_LABEL",
            "rate",
            "lo",
            "hi",
            "Ever 60+ by MOB 12, by vintage quarter",
            "% of vintage",
            color="#E08A3C",
        ),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
    st.caption(f"{C.DISCLAIMER_CENSORING} Only quarters observable at MOB 12 are shown.")
methodology.definitions()
