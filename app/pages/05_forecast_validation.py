"""05 Forecast and Validation: can cohort run-off be forecast out-of-time better than
naive baselines? (Q5)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd
import streamlit as st

from app.components import charts, kpi_cards, methodology, tables
from app.components.formatting import PLOTLY_CONFIG, ci, num, pct
from app.components.navigation import banner, page_setup, section
from src.services import forecast
from src.utils import constants as C

page_setup(
    "Forecast & Validation",
    "Absorbing Markov run-off forecasts, validated out-of-time against naive baselines.",
    "Q5 Can cohort run-off be forecast 3/6/12 months ahead better than naive baselines?",
    use_filters=False,
)
banner(
    f"{C.DISCLAIMER_RUNOFF}. The forecast object is the set of accounts in DORMANT or 1-29 to 120-149 at the "
    "origin month.",
    "info",
)
st.caption(C.DISCLAIMER_SOURCE)

with st.expander("Model limitations", expanded=True):
    hd = forecast.headline()
    st.markdown(
        "\n".join(
            [
                "- First-order, time-homogeneous chain estimated on pooled transitions; the stationarity and "
                "MOB tests below show where those assumptions fail.",
                "- State-share error is dominated by the large 1-29 and PAID-OFF shares; per-state errors and the "
                "charge-off count calibration are shown next to it.",
                f"- Charge-offs are rare: the count calibration covers {hd['calibration_pairs']} origin/horizon pairs "
                f"and the actual count falls inside the 95% predictive interval in {hd['calibration_inside']} of them.",
                "- Accounts with no record at the target month are counted as missing; the primary comparison uses "
                f"the full cohort forecast against observed accounts (mean missing share {pct(hd['missing_share_mean'])}).",
                "- No balances, so the forecast is in account counts, not exposure.",
            ]
        )
    )

section("Current-mix run-off from relative month 0")
fc = forecast.current_forecast()
st.plotly_chart(
    charts.runoff_stack(fc, "Projected composition of the month-0 cohort"),
    config=PLOTLY_CONFIG,
    theme=None,
    width="stretch",
)
w = fc.pivot_table(index="STATE", columns="horizon", values="count", aggfunc="first").reindex(
    C.MARKOV_ORDER
)
w.columns = [f"{c}M" if c else "Origin" for c in w.columns]
tables.show(w.round(1).reset_index())

section("Out-of-time backtest")
h = (
    st.segmented_control(
        "Horizon", [3, 6, 12], default=12, format_func=lambda v: f"{v}M", key="fv_h"
    )
    or 12
)
metric = st.selectbox(
    "Error metric",
    list(forecast.METRIC_LABELS),
    format_func=forecast.METRIC_LABELS.get,
    key="fv_metric",
)
hh = hd["headline"][str(h)] if str(h) in hd["headline"] else hd["headline"][h]
kpi_cards.metric_cards(
    [
        {
            "label": f"MARKOV MAE, ORIGIN M{hh['latest_origin']}",
            "value": hh["markov:mae_pp:latest"],
            "display": f"{hh['markov:mae_pp:latest']:.2f} pp",
            "lines": [
                ci(hh["markov:mae_pp:latest_lo"], hh["markov:mae_pp:latest_hi"], "num", 2) + " pp"
            ],
        },
        {
            "label": "PERSISTENCE MAE",
            "value": hh["persistence:mae_pp:latest"],
            "display": f"{hh['persistence:mae_pp:latest']:.2f} pp",
            "lines": ["baseline 1"],
        },
        {
            "label": "STATIC-MIX MAE",
            "value": hh["static_mix:mae_pp:latest"],
            "display": f"{hh['static_mix:mae_pp:latest']:.2f} pp",
            "lines": ["baseline 2"],
        },
        {
            "label": "SKILL VS PERSISTENCE",
            "value": hh["skill_vs_persistence:mae:latest"],
            "display": f"{hh['skill_vs_persistence:mae:latest']:.2f}",
            "lines": [
                ci(
                    hh["skill_vs_persistence:mae:latest_lo"],
                    hh["skill_vs_persistence:mae:latest_hi"],
                    "num",
                    2,
                ),
                f"wins at {hh['wins_vs_persistence:mae']} of {hh['n_origins']} origins",
            ],
        },
        {
            "label": "SKILL VS STATIC MIX",
            "value": hh["skill_vs_static_mix:mae:latest"],
            "display": f"{hh['skill_vs_static_mix:mae:latest']:.2f}",
            "lines": [
                ci(
                    hh["skill_vs_static_mix:mae:latest_lo"],
                    hh["skill_vs_static_mix:mae:latest_hi"],
                    "num",
                    2,
                ),
                f"wins at {hh['wins_vs_static_mix:mae']} of {hh['n_origins']} origins",
            ],
        },
    ],
    per_row=5,
)
st.caption(
    "Skill = 1 - error(model) / error(baseline). Positive means the Markov model beats the baseline. "
    "Where a baseline wins on a metric, the table below shows it."
)

err = forecast.errors(h, metric)
st.plotly_chart(
    charts.model_errors(
        err, forecast.MODEL_LABELS, f"{forecast.METRIC_LABELS[metric]}, {h}M ahead", "pp"
    ),
    config=PLOTLY_CONFIG,
    theme=None,
    width="stretch",
)
avg = (
    err.assign(abs_value=err.value.abs())
    .groupby("model")
    .abs_value.mean()
    .rename("Mean |error| (pp)")
)
latest = err[err.origin == err.origin.max()].set_index("model").value.rename("Latest origin (pp)")
summ = pd.concat([latest, avg], axis=1).reindex(
    [m for m in forecast.MODEL_LABELS if m in avg.index]
)
summ.index = [forecast.MODEL_LABELS[m] for m in summ.index]
tables.show(summ.round(3).reset_index().rename(columns={"index": "Model"}))

pairs = forecast.pairs()
origins = sorted(pairs[pairs.horizon == h].origin.unique())
o = st.select_slider(
    "Origin for the actual-vs-forecast view", origins, value=origins[-1], key="fv_origin"
)
avf = forecast.actual_vs_forecast(o, h)
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(
        charts.forecast_vs_actual(avf, f"Forecast vs actual, origin M{o}, {h}M"),
        config=PLOTLY_CONFIG,
        theme=None,
        width="stretch",
    )
with c2:
    tables.show(
        avf.assign(forecast=avf.forecast * 100, actual=avf.actual * 100)
        .round(3)
        .rename(columns={"forecast": "Forecast %", "actual": "Actual %", "error_pp": "Error (pp)"})
    )

section("Charge-off count calibration")
cal = forecast.calibration()
st.plotly_chart(
    charts.calibration_chart(
        cal, "Predicted vs actual charge-offs (95% bootstrap predictive interval)"
    ),
    config=PLOTLY_CONFIG,
    theme=None,
    width="stretch",
)
st.caption(
    f"Actual inside the interval in {int(cal.inside.sum())} of {len(cal)} pairs. Predictive intervals combine "
    "parameter uncertainty (bootstrap matrices and cohorts) with binomial outcome noise."
)

section("Is first-order Markov enough?")
mh, mb, ht = forecast.mob_tests()
st_tab, st_sum = forecast.stationarity()
c1, c2 = st.columns(2)
with c1:
    st.markdown("**MOB-band homogeneity (chi-square per origin row)**")
    tables.show(
        mh.assign(
            p_value=mh.p_value.map(lambda v: f"{v:.2g}"), chi2=mh.chi2.round(1), n=mh.n.map(num)
        )
    )
    st.markdown("**Stationarity: first vs second half of the window**")
    tables.show(
        st_tab.assign(
            p_value=st_tab.p_value.map(lambda v: f"{v:.2g}"),
            chi2=st_tab.chi2.round(1),
            total_variation=st_tab.total_variation.round(4),
            n=st_tab.n.map(num),
        )
    )
    oot = st_sum["oot_mae_pp_origin_m12_h12"]
    st.caption(
        f"Rows rejecting homogeneity at 5%: {st_sum['rows_rejecting_at_5pct']} of {st_sum['rows_tested']}. "
        f"Out-of-time 12M MAE from origin M-12: first-half matrix {oot['first_half']:.2f} pp vs expanding "
        f"matrix {oot['expanding_to_m12']:.2f} pp. Chi-square on sparse rows is approximate."
    )
with c2:
    st.markdown("**Band probabilities (mature minus early, with 95% CI)**")
    d = mb[mb.band == "mature minus early"]
    tables.show(
        pd.DataFrame(
            {
                "Transition": d.FROM_STATE + " to " + d.TO_STATE,
                "Difference (pp)": (d.p * 100).round(2),
                "95% CI": [ci(a * 100, b * 100, "pp", 2) for a, b in zip(d.lo, d.hi, strict=True)],
            }
        )
    )
    st.markdown("**History test (Anderson-Goodman): does the previous state matter?**")
    tables.show(ht.assign(p_value=ht.p_value.map(lambda v: f"{v:.2g}"), chi2=ht.chi2.round(1)))
mob_avg = hh.get("mob_conditioned:mae_pp:mean_abs")
st.markdown(
    f"At {h}M the MOB-conditioned model averages {mob_avg:.2f} pp MAE across origins against "
    f"{hh['markov:mae_pp:mean_abs']:.2f} pp for the pooled expanding model and "
    f"{hh['markov_rolling:mae_pp:mean_abs']:.2f} pp for the 24M rolling model."
    if mob_avg is not None
    else C.MSG_UNAVAILABLE
)
methodology.definitions()
