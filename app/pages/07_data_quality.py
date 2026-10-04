"""07 Data Quality: can the data be trusted for these purposes, and where are its limits? (Q7)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import html

import pandas as pd
import streamlit as st

from app.components import kpi_cards, methodology, tables
from app.components.formatting import num, pct
from app.components.navigation import page_setup, section
from src.services import quality
from src.utils import constants as C

page_setup(
    "Data Quality",
    "Every rule applied to the raw files, with its result. Problems are shown, not hidden.",
    "Q7 Can the data be trusted for these purposes, and where are its limits?",
    use_filters=False,
)
st.caption(C.DISCLAIMER_SOURCE)

m = quality.metrics()
s = quality.summary()
kpi_cards.metric_cards(
    [
        {
            "label": "APPLICATION ROWS",
            "value": m["app_rows"],
            "display": num(m["app_rows"]),
            "lines": [f"{num(m['app_unique_ids'])} unique applicants"],
        },
        {
            "label": "CREDIT ROWS",
            "value": m["credit_rows"],
            "display": num(m["credit_rows"]),
            "lines": [f"{num(m['credit_clients'])} unique credit clients"],
        },
        {
            "label": "MATCHED CLIENTS",
            "value": m["matched_clients"],
            "display": num(m["matched_clients"]),
            "lines": [
                f"{pct(m['matched_clients'] / m['credit_clients'])} of credit clients",
                f"{pct(m['matched_clients'] / m['app_unique_ids'])} of applicants",
            ],
        },
        {
            "label": "CHECKS",
            "value": float(sum(s.values())),
            "display": num(sum(s.values())),
            "lines": [f"{s['PASS']} PASS, {s['WARNING']} WARNING, {s['FAIL']} FAIL"],
        },
    ],
    per_row=4,
)

section("Checks")
chk = quality.checks()


def _fmt(v: object) -> str:
    if isinstance(v, float) and 0 < abs(v) < 1:
        return pct(v)
    if isinstance(v, (int, float)):
        return num(v)
    return str(v)


rows = "".join(
    f"<tr><td>{html.escape(r.group)}</td><td>{html.escape(r.check)}</td><td style='text-align:right'>"
    f"{html.escape(_fmt(r.value))}</td><td>{html.escape(r.rule)}</td>"
    f"<td><span class='ccrm-chip {r.status}'>{r.status}</span></td><td>{html.escape(r.detail or '')}</td></tr>"
    for r in chk.itertuples(index=False)
)
st.markdown(
    "<div class='ccrm-card' style='min-height:0;overflow-x:auto'><table style='width:100%;font-size:12.5px;"
    "border-collapse:collapse'><tr style='text-align:left;color:#6B7280'><th>Group</th><th>Check</th>"
    "<th>Value</th><th>Rule</th><th>Status</th><th>Detail</th></tr>" + rows + "</table></div>",
    unsafe_allow_html=True,
)
tables.download_csv(chk, "Download checks (CSV)", "data_quality_checks.csv", "dq_dl")

rep = quality.report()
section("File truncation and left truncation")
tr, lt = rep["truncation"], rep["left_truncation"]
st.markdown(
    f"credit_record.csv has {num(tr['row_count'])} data rows; Excel's limit is {num(tr['excel_row_limit'])}. "
    f"The file is sorted by ID and its last client is the largest credit ID. {num(tr['app_ids_above_cut'])} "
    f"application IDs lie above it and {num(tr['app_ids_above_cut_matched'])} of them have a credit record, "
    f"while {num(tr['app_ids_at_or_below_cut_matched'])} of {num(tr['app_ids_at_or_below_cut'])} application IDs "
    f"at or below it do. That final client's earliest record is already "
    f"{'PAID-OFF' if tr['final_client_first_status_is_c'] else 'not PAID-OFF'}. "
    f"Test result: **{'fired' if tr['fired'] else 'not fired'}**; final client "
    f"{'excluded from analysis' if tr['excluded'] else 'kept'}."
)
st.markdown(
    f"Left truncation: earliest vintage M{lt['first_vintage_month']} has {num(lt['first_vintage_size'])} accounts "
    f"(median vintage {num(lt['median_vintage_size'])}); {pct(lt['first_vintage_b0_share'])} start in 1-29 DPD; "
    f"non-1-29 share at MOB 0 is {pct(lt['early_non_b0_share'], 2)} in the first three vintages vs "
    f"{pct(lt['later_non_b0_share'], 2)} later. Test **{'fired' if lt['fired'] else 'not fired'}**."
)

section("Status semantics evidence (raw transition counts)")
st.dataframe(quality.raw_transition_matrix(), width="stretch")
st.caption(
    f"C to C: {num(m['c_to_c'])} of {num(m['c_transitions_total'])} transitions out of C; C to an open status: "
    f"{num(m['c_to_open'])}. Active-to-X exits: {num(m['active_to_x_exits'])} ({num(m['active_to_x_clients'])} "
    f"clients); {pct(rep['dormant_return_share'], 0)} of exiting clients later return. Leading X: "
    f"{num(m['first_status_x_clients'])} clients start with X; {num(m['x_only_clients'])} are never open."
)

section("Charge-off (5) to non-5 anomalies")
an = quality.anomalies()
c1, c2 = st.columns([2, 3])
with c1:
    tables.show(an.rename(columns={"FROM_STATE": "From", "TO_STATE": "To", "n": "Transitions"}))
with c2:
    st.markdown(
        f"On consecutive non-X rows, status 5 is followed by a non-5 status {num(m['co_to_nonco_consecutive_nonx'])} "
        f"times out of {num(m['co_transitions_nonx'])}. These rows are kept in an anomaly table, never in the "
        "roll-rate matrices; the model enforces CHARGE-OFF as absorbing and the stress module reports a "
        "sensitivity with the raw leak."
    )

section("Recomputed audit values vs pilot targets")
pr = quality.pilot_reconciliation()
tables.show(pr.assign(agrees=pr.agrees.map({True: "PASS", False: "WARNING"})))
st.caption(
    "Pilot values from the project brief are verification targets only; every number is recomputed "
    "from the raw files. Differences are explained in docs/data_audit.md."
)

section("Missing values (application file)")
nul = pd.DataFrame(rep["app_nulls"]).rename(columns={"column_name": "Column", "n_null": "Missing"})
nul["Share"] = nul.Missing / m["app_rows"]
tables.show(nul.assign(Share=nul.Share.map(pct)))
methodology.definitions()
