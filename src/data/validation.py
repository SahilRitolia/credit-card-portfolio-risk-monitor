"""Data-quality rules (PASS / WARNING / FAIL), the file-truncation test and the
reconciliation of recomputed audit values with the pilot values in the configured reproducibility targets.

All inputs are measured values from ``dq_metrics`` (sql/02_data_quality.sql) and other SQL
tables; nothing here reads raw rows.
"""

from __future__ import annotations

import math
from typing import Any

PASS, WARNING, FAIL = "PASS", "WARNING", "FAIL"


def file_truncation_test(
    row_count: int, last_id: str | None, m: dict[str, float], params: dict
) -> dict:
    """Is credit_record.csv cut at Excel's row limit, truncating the final client?

    Evidence combined: (a) the data row count equals the Excel limit; (b) the final client in
    file order is the largest credit ID and no application ID above it has any credit record
    while every application ID at or below it does (a hard cut in an ID-sorted file);
    (c) the final client's earliest record is already PAID-OFF, which is rare for a first
    record. The test fires on (a) and (b); (c) is reported as supporting evidence.
    """
    limit = int(params["truncation"]["excel_row_limit"])
    at_limit = int(row_count) == limit
    last_is_max = last_id is not None and float(last_id) == m["max_credit_id"]
    above = m["app_ids_above_max_credit_id"]
    matched_above = m["matched_above_max_credit_id"]
    below = m["app_ids_at_or_below_max_credit_id"]
    matched_below = m["matched_at_or_below_max_credit_id"]
    hard_cut = above > 0 and matched_above == 0 and below > 0 and matched_below == below
    fired = bool(at_limit and last_is_max and hard_cut)
    first_c_rate = (
        m["first_status_c_clients"] / m["credit_clients"] if m["credit_clients"] else math.nan
    )
    return {
        "row_count": int(row_count),
        "excel_row_limit": limit,
        "row_count_equals_limit": at_limit,
        "final_client_id": last_id,
        "final_client_is_max_id": bool(last_is_max),
        "final_client_records": m["max_credit_id_records"],
        "final_client_first_month": m["max_credit_id_first_month"],
        "final_client_first_status_is_c": bool(m["max_credit_id_first_status_is_c"]),
        "first_record_c_rate_all_clients": first_c_rate,
        "app_ids_above_cut": above,
        "app_ids_above_cut_matched": matched_above,
        "app_ids_at_or_below_cut": below,
        "app_ids_at_or_below_cut_matched": matched_below,
        "fired": fired,
        "excluded": bool(fired and params["truncation"]["exclude_final_client_if_truncated"]),
    }


def _check(group: str, name: str, value: Any, rule: str, status: str, detail: str = "") -> dict:
    return {
        "group": group,
        "check": name,
        "value": value,
        "rule": rule,
        "status": status,
        "detail": detail,
    }


def dq_checks(m: dict[str, float], extra: dict[str, Any], params: dict) -> list[dict]:
    """Evaluate every data-quality rule shown on the Data Quality page."""
    dq = params["dq"]
    out: list[dict] = []
    out.append(
        _check(
            "Volume", "Application rows", m["app_rows"], "> 0", PASS if m["app_rows"] > 0 else FAIL
        )
    )
    out.append(
        _check(
            "Volume", "Credit rows", m["credit_rows"], "> 0", PASS if m["credit_rows"] > 0 else FAIL
        )
    )
    out.append(
        _check(
            "Volume",
            "Unique applicants",
            m["app_unique_ids"],
            "> 0",
            PASS if m["app_unique_ids"] > 0 else FAIL,
        )
    )
    out.append(
        _check(
            "Volume",
            "Unique credit clients",
            m["credit_clients"],
            "> 0",
            PASS if m["credit_clients"] > 0 else FAIL,
        )
    )
    out.append(
        _check(
            "Linkage",
            "Matched clients (both files)",
            m["matched_clients"],
            "> 0",
            PASS if m["matched_clients"] > 0 else FAIL,
        )
    )
    rate_c = m["matched_clients"] / m["credit_clients"]
    out.append(
        _check(
            "Linkage",
            "Credit clients with demographics",
            rate_c,
            f">= {dq['min_match_rate_warn']:.0%} else WARNING",
            PASS if rate_c >= dq["min_match_rate_warn"] else WARNING,
            "Segmentation uses matched clients only.",
        )
    )
    rate_a = m["matched_clients"] / m["app_unique_ids"]
    out.append(
        _check(
            "Linkage",
            "Applicants with credit history",
            rate_a,
            "informational; low rate = WARNING",
            WARNING if rate_a < dq["min_match_rate_warn"] else PASS,
            "Most application IDs have no credit record (see file truncation).",
        )
    )
    out.append(
        _check(
            "Uniqueness",
            "Duplicate (ID, month) in credit file",
            m["credit_dup_id_month"],
            "= 0",
            PASS if m["credit_dup_id_month"] == 0 else FAIL,
        )
    )
    out.append(
        _check(
            "Uniqueness",
            "Duplicated application IDs",
            m["app_duplicated_ids"],
            "= 0 else WARNING (kept once, flagged)",
            PASS if m["app_duplicated_ids"] == 0 else WARNING,
            f"{int(extra['conflicting_dup_ids'])} of them disagree on attributes and are excluded from segmentation.",
        )
    )
    out.append(
        _check(
            "Validity",
            "Invalid status values",
            m["credit_invalid_status"],
            "= 0",
            PASS if m["credit_invalid_status"] == 0 else FAIL,
        )
    )
    nulls = m["credit_null_id"] + m["credit_null_month"]
    out.append(
        _check(
            "Validity",
            "Null ID or month in credit file",
            nulls,
            "= 0",
            PASS if nulls == 0 else FAIL,
        )
    )
    out.append(
        _check(
            "Validity",
            "Month range",
            f"{int(m['month_min'])} to {int(m['month_max'])}",
            "max = 0 (relative index)",
            PASS if m["month_max"] == 0 else FAIL,
        )
    )
    out.append(
        _check(
            "Continuity",
            "Month gaps within client histories",
            m["month_gap_pairs"],
            "= 0 else WARNING (gaps are never filled)",
            PASS if m["month_gap_pairs"] == 0 else WARNING,
            f"{int(m['month_successive_pairs'])} successive record pairs checked with LAG.",
        )
    )
    out.append(
        _check(
            "History",
            "Single-record clients",
            m["single_record_clients"],
            "informational",
            PASS,
            "No transition can be observed for them.",
        )
    )
    out.append(
        _check(
            "History",
            f"Clients with fewer than {dq['short_history_months']} records",
            m["short_history_clients"],
            "informational",
            PASS,
        )
    )
    out.append(
        _check(
            "History",
            "Clients observed for all 61 months",
            m["full_window_clients"],
            "informational",
            PASS,
        )
    )
    lead_x = m["first_status_x_clients"] / m["credit_clients"]
    out.append(
        _check(
            "History",
            "Clients whose first record is X (leading dormant months)",
            lead_x,
            f"<= {dq['max_leading_x_share_warn']:.0%} else WARNING",
            PASS if lead_x <= dq["max_leading_x_share_warn"] else WARNING,
            "MOB starts at the first non-X month, not the first record.",
        )
    )
    out.append(
        _check(
            "History",
            "Clients that are never open (X only)",
            m["x_only_clients"],
            "informational",
            PASS,
            "Kept in the audit, excluded from vintages and transitions.",
        )
    )
    out.append(
        _check(
            "Maturity",
            "Immature vintages (fewer than 12 observable MOB)",
            extra["immature_vintages"],
            "informational",
            WARNING if extra["immature_vintages"] > 0 else PASS,
            "Their curves are truncated at the last observable MOB.",
        )
    )
    c_ok = m["c_to_open"] <= 0.001 * max(m["c_transitions_total"], 1)
    out.append(
        _check(
            "Semantics",
            "C returns to an open status",
            m["c_to_open"],
            "<= 0.1% of transitions out of C",
            PASS if c_ok else FAIL,
            "Evidence that C is an absorbing exit (PAID-OFF), not CURRENT.",
        )
    )
    out.append(
        _check(
            "Semantics",
            "Dormant (X) exits that later return",
            extra["dormant_return_share"],
            "informational",
            PASS,
            "X is a transient DORMANT state, not an exit.",
        )
    )
    co_share = m["co_to_nonco_consecutive_nonx"] / max(m["co_transitions_nonx"], 1)
    out.append(
        _check(
            "Semantics",
            "Charge-off (5) followed by a non-5 status",
            co_share,
            f"<= {dq['max_anomaly_share_warn']:.0%} else WARNING",
            PASS if co_share <= dq["max_anomaly_share_warn"] else WARNING,
            "Flagged in the anomaly table; the model enforces absorption; sensitivity reported.",
        )
    )
    tr = extra["truncation"]
    out.append(
        _check(
            "Truncation",
            "credit_record.csv cut at Excel row limit",
            "fired" if tr["fired"] else "not fired",
            "row count = Excel limit and hard ID cut => WARNING",
            WARNING if tr["fired"] else PASS,
            "Final client excluded from analysis." if tr["excluded"] else "",
        )
    )
    lt = extra["left_truncation"]
    out.append(
        _check(
            "Truncation",
            "Left truncation of earliest vintages",
            "fired" if lt["fired"] else "not fired",
            "early MOB-0 mix or size pile-up => WARNING",
            WARNING if lt["fired"] else PASS,
        )
    )
    out.append(
        _check(
            "Missing values",
            "OCCUPATION_TYPE missing",
            m["app_occupation_null"] / m["app_rows"],
            "informational",
            PASS,
            "Not used by any metric.",
        )
    )
    out.append(
        _check(
            "Missing values",
            "DAYS_EMPLOYED sentinel 365243",
            m["app_days_employed_sentinel"],
            "set to NULL",
            WARNING if m["app_days_employed_sentinel"] > 0 else PASS,
            "Converted to missing in 03_cleaning.sql.",
        )
    )
    return out


PILOT_ITEMS: list[tuple[str, str]] = [
    ("credit_rows", "credit_rows"),
    ("credit_clients", "credit_clients"),
    ("credit_dup_id_month", "credit_dup_id_month"),
    ("month_min", "month_min"),
    ("month_max", "month_max"),
    ("month_gap_pairs", "month_gap_pairs"),
    ("matched_clients", "matched_clients"),
    ("application_only", "application_only"),
    ("credit_only", "credit_only"),
    ("first_status_x_clients", "first_status_x_clients"),
    ("first_status_0_clients", "first_status_0_clients"),
    ("first_status_c_clients", "first_status_c_clients"),
    ("c_to_c", "c_to_c"),
    ("c_transitions_total", "c_transitions_total"),
    ("c_preceded_by_open", "c_preceded_by_open"),
    ("open_preceded_by_c", "open_preceded_by_c"),
    ("active_to_x_exits", "active_to_x_exits"),
    ("active_to_x_clients", "active_to_x_clients"),
    ("x_to_active_reentries", "x_to_active_reentries"),
    ("x_to_active_clients", "x_to_active_clients"),
    ("co_to_nonco_consecutive_nonx", "co_to_nonco_consecutive_nonx"),
    ("co_transitions_nonx", "co_transitions_nonx"),
    ("open_accounts_m0", "open_accounts_m0"),
    ("open_accounts_m1", "open_accounts_m1"),
    ("nonx_m1", "nonx_m1"),
    ("x_only_clients", "x_only_clients"),
]


def reconcile_pilot(computed: dict[str, float], params: dict, tolerance: float = 0.0) -> list[dict]:
    """Compare recomputed audit values with the pilot targets (exact match by default)."""
    targets = params.get("pilot_targets", {})
    rows = []
    for key, mkey in PILOT_ITEMS + [
        (k, k) for k in ("new_co_12m_from_m12", "open_0_4_at_m12", "vintage_m60_clients")
    ]:
        if key not in targets or mkey not in computed:
            continue
        pilot = float(targets[key])
        got = float(computed[mkey])
        diff = got - pilot
        ok = abs(diff) <= tolerance * max(abs(pilot), 1.0)
        rows.append(
            {"item": key, "pilot": pilot, "computed": got, "difference": diff, "agrees": bool(ok)}
        )
    return rows
