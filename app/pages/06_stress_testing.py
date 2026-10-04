"""06 Stress Testing: how much illustrative expected loss moves under stress, and what
would double it (Q6). EAD and LGD are assumptions; the source has no balances."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app.components import charts, kpi_cards, methodology, tables
from app.components.formatting import PLOTLY_CONFIG, ci, money, num, pct
from app.components.navigation import page_setup, section
from src.services import stress
from src.utils import constants as C

page_setup(
    "Stress Testing",
    "Scenario transform of the transition matrix and illustrative expected loss on the month-0 cohort.",
    "Q6 How much does expected loss move under stress, and what would double it?",
    use_filters=False,
)
st.warning(C.DISCLAIMER_EL)
st.caption(f"{C.LABEL_EAD} {C.LABEL_LGD} {C.DISCLAIMER_SOURCE}")

cfg = stress.config()
cur = cfg["currency"]
presets = cfg["presets"]
c0, c1, c2, c3, c4, c5 = st.columns([1.2, 1, 1, 1, 1, 1])
preset = c0.selectbox("Preset", list(presets) + ["CUSTOM"], key="st_preset")
pm = presets.get(preset, presets["BASE"])
m = c1.slider(
    "Deterioration m",
    0.0,
    5.0,
    float(pm["m"]),
    0.05,
    key=f"st_m_{preset}",
    help="Multiplies probabilities of moving to a more severe bucket or charge-off.",
)
c = c2.slider(
    "Cure adjustment c",
    -1.0,
    1.0,
    float(pm["c"]),
    0.05,
    key=f"st_c_{preset}",
    help="Scales probabilities of moving to a less severe bucket or paid-off by (1 + c).",
)
ead = c3.number_input(
    f"EAD per open account ({cur})",
    0.0,
    1_000_000.0,
    float(cfg["ead"]),
    100.0,
    key="st_ead",
    help=C.LABEL_EAD,
)
lgd = c4.slider("LGD", 0.0, 1.0, float(cfg["lgd"]), 0.05, key="st_lgd", help=C.LABEL_LGD)
h = c5.slider("Horizon (months)", 1, int(cfg["max_horizon"]), 12, key="st_h")
inc_dormant = st.toggle(
    "Sensitivity: include DORMANT accounts in the EAD base", value=False, key="st_dorm"
)

r = stress.scenario(m, c, ead, lgd, h, inc_dormant)
if not r["matrix_ok"]:
    st.error("Stressed matrix failed the row-sum check.")
kpi_cards.metric_cards(
    [
        {
            "label": f"EL {h}M ({preset})",
            "value": r["el"],
            "display": money(r["el"], cur),
            "lines": [
                ci(r["el_lo"], r["el_hi"], "money", cur=cur),
                "illustrative; assumed EAD and LGD",
            ],
        },
        {
            "label": f"BASE EL {h}M",
            "value": r["base"],
            "display": money(r["base"], cur),
            "lines": ["m = 1, c = 0"],
        },
        {
            "label": "INCREMENTAL EL",
            "value": r["incremental"],
            "display": money(r["incremental"], cur),
            "lines": [ci(r["incremental_lo"], r["incremental_hi"], "money", cur=cur)],
        },
        {
            "label": "UPLIFT VS BASE",
            "value": r["uplift"],
            "display": pct(r["uplift"], 0),
            "lines": [ci(r["uplift_lo"], r["uplift_hi"], "pct", 0)],
        },
        {
            "label": "EXPECTED CHARGE-OFFS",
            "value": r["expected_chargeoffs"],
            "display": num(r["expected_chargeoffs"], 1),
            "lines": ["accounts, model-implied"],
        },
    ],
    per_row=5,
)
st.caption(C.DISCLAIMER_EL)

col1, col2 = st.columns(2)
with col1:
    st.plotly_chart(
        charts.el_contribution(
            r["contributions"], cur, f"Where the {h}M loss comes from (by origin state)"
        ),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
with col2:
    pt = stress.preset_table(ead, lgd, inc_dormant)
    st.plotly_chart(
        charts.scenario_bars(pt, cur, "Preset scenarios, 6M and 12M (95% bootstrap intervals)"),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )

section("Preset scenario table")
tables.show(pt.round(2))
st.caption(
    f"{C.DISCLAIMER_EL} Presets are illustrative and user-editable; they are not regulatory or "
    "macro-calibrated."
)
tables.download_csv(
    stress.download_table(m, c, ead, lgd, h, inc_dormant),
    "Download scenario table (CSV)",
    "stress_scenarios.csv",
    "st_dl",
)

section("Reverse stress and calibration anchor")
rv = stress.reverse_stress()
an = stress.calibration_anchor()
k1, k2 = st.columns(2)
with k1:
    kpi_cards.value_card(
        "M THAT DOUBLES BASE 12M EL",
        f"{rv['m']:.2f}",
        [ci(rv["lo"], rv["hi"], "num", 2), "at c = 0; independent of EAD and LGD"],
        "Smallest deterioration multiplier whose 12-month EL is twice the base, by bisection.",
    )
with k2:
    kpi_cards.value_card(
        "CALIBRATION ANCHOR",
        f"{an['predicted_co']:.1f} vs {an['actual_co']:.0f}",
        [
            f"model-implied vs observed charge-offs, origin M{int(an['origin'])}, 12M",
            f"95% predictive interval {an['pred_lo']:.0f} to {an['pred_hi']:.0f}",
        ],
        "Backtest check of the base matrix on observed charge-off counts.",
        ["PASS"] if an["inside"] else ["WARNING"],
    )

with st.expander("Method and limitations", expanded=False):
    st.markdown(
        "\n".join(
            [
                "- EL_h = sum over origin states of n_s x EAD x PD_h(s) x LGD with PD_h(s) = (P'^h)[s, CHARGE-OFF].",
                "- Cohort: accounts in 1-29 to 120-149 at relative month 0 carry EAD; DORMANT carries EAD 0 unless "
                "the sensitivity toggle is on; accounts already charged off or paid off are excluded.",
                "- Scenario transform: worse transitions x m (capped at 1), benign transitions x (1 + c), the "
                "residual goes to staying or dormant; rows always sum to 1.",
                "- Base matrix re-estimated live from the committed transition cube; intervals use precomputed "
                "client-level bootstrap replicate matrices.",
                "- Flat EAD, no recoveries timing, no discounting, no new originations, not IFRS 9 / CECL, "
                "12-month horizon only.",
            ]
        )
    )
methodology.definitions()
