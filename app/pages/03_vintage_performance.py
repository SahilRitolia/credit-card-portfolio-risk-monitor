"""03 Vintage Performance: do newer vintages deteriorate faster at the same MOB? (Q3)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from app.components import charts, methodology, tables
from app.components.formatting import PLOTLY_CONFIG, ci, pct
from app.components.navigation import banner, page_setup, section
from src.services import vintage
from src.utils import constants as C

page_setup(
    "Vintage Performance",
    "Cumulative delinquency by months on book for each opening cohort, observable cells only.",
    "Q3 Do newer vintages deteriorate faster than older ones at the same MOB?",
    use_filters=False,
)
st.warning(C.DISCLAIMER_CENSORING)
st.caption(C.DISCLAIMER_SOURCE)

opts = vintage.metric_options()
c1, c2 = st.columns([1, 3])
metric = c1.selectbox("Metric", list(opts), format_func=lambda k: opts[k], key="vp_metric")
quarters = vintage.quarter_options()
labels = dict(quarters)
default = [q for q, _ in quarters if q < 20][::4]
sel = c2.multiselect(
    "Vintage quarters",
    [q for q, _ in quarters],
    default=default,
    format_func=lambda q: labels[q],
    key="vp_quarters",
)

lt = vintage.left_truncation()
if lt["fired"]:
    banner(
        "Left-truncation test fired: the earliest vintages may contain pre-existing accounts.",
        "neg",
    )
else:
    banner(
        f"Left-truncation check: earliest vintage (M{lt['first_vintage_month']}) has "
        f"{lt['first_vintage_size']:,.0f} accounts versus a median vintage of {lt['median_vintage_size']:,.0f}, and "
        f"{pct(lt['first_vintage_b0_share'])} start in 1-29 DPD. No sign of pre-existing accounts.",
        "info",
    )

curves = vintage.quarterly_curves(metric, sel or None)
if curves.empty:
    st.info(C.MSG_INSUFFICIENT)
else:
    st.plotly_chart(
        charts.vintage_curves(curves, f"{opts[metric]} by months on book"),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
    st.caption(
        "Each curve stops at the last MOB at which every month of the quarter is observable."
    )

section("Vintage x MOB heatmap")
hm = vintage.heatmap(metric)
st.plotly_chart(
    charts.vintage_heatmap(hm, f"{opts[metric]} (blank = not yet observable)"),
    config=PLOTLY_CONFIG,
    theme=None,
    width="stretch",
)

section("Checkpoint comparison at MOB 6 / 12 / 18 / 24")
cp = vintage.checkpoints(metric)
if cp.empty:
    st.info(C.MSG_INSUFFICIENT)
else:
    wide = (
        cp.pivot_table(index="VINTAGE_LABEL", columns="MOB", values="rate", aggfunc="first") * 100
    )
    order = cp.drop_duplicates("VINTAGE_LABEL").sort_values("VINTAGE_QTR").VINTAGE_LABEL
    wide = wide.reindex(order)
    wide.columns = [f"MOB {c} %" for c in wide.columns]
    n = cp[cp.MOB.min() == cp.MOB].set_index("VINTAGE_LABEL").n_accounts.reindex(order)
    wide.insert(0, "Accounts", n.values)
    ci12 = cp[cp.MOB == 12].set_index("VINTAGE_LABEL")
    wide["MOB 12 95% CI"] = [
        ci(ci12.lo.get(v), ci12.hi.get(v), "pct", 2) if v in ci12.index else "" for v in wide.index
    ]
    tables.show(wide.reset_index().rename(columns={"VINTAGE_LABEL": "Vintage"}).round(2))
    comp = vintage.comparison(metric)
    if not comp.empty:
        ct = pd.DataFrame(
            {
                "MOB": comp.MOB,
                "Oldest four quarters": comp.old_quarters,
                "Rate (old)": [pct(v, 2) for v in comp.old_rate],
                "Most recent four quarters": comp.recent_quarters,
                "Rate (recent)": [pct(v, 2) for v in comp.recent_rate],
                "Difference (pp)": (comp["diff"] * 100).round(2),
                "95% CI (pp)": [
                    ci(lo * 100, hi * 100, "pp", 2) for lo, hi in zip(comp.lo, comp.hi, strict=True)
                ],
                "Verdict": comp.verdict,
            }
        )
        tables.show(ct)
        st.caption(
            "Verdict is 'higher' or 'lower' only when the bootstrap interval of the difference "
            "excludes zero; otherwise the data do not distinguish the cohorts."
        )

with st.expander("First-delinquency timing and maximum severity"):
    fd = vintage.first_delinquency()
    dist = fd.groupby("MOB").n.sum().reset_index()
    dist["rate"] = dist.n / dist.n.sum()
    st.plotly_chart(
        charts.line_rate(
            dist,
            "MOB",
            "rate",
            "MOB of first 30+ (all vintages, accounts ever 30+)",
            "% of accounts ever 30+",
            "Months on book",
            n_col="n",
        ),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
    ms = vintage.max_severity()
    piv = (
        ms.pivot_table(
            index="VINTAGE_QTR", columns="MAX_STATE", values="share", aggfunc="first"
        ).fillna(0)
        * 100
    )
    piv.index = [labels.get(int(i), str(i)) for i in piv.index]
    tables.show(piv.round(2).reset_index().rename(columns={"index": "Vintage"}))
methodology.definitions()
