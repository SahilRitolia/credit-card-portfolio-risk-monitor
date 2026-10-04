"""Execute the DuckDB SQL layer (``sql/01_*.sql`` .. ``sql/10_*.sql``) in order.

SQL files contain ``{{NAME}}`` template slots that are filled from ``config/params.yaml``
by :func:`template_context`. Python downstream reads the tables these scripts create and
never recomputes them (except in reconciliation tests).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.utils.helpers import SQL_DIR, load_params
from src.utils.logging import get_logger

log = get_logger("sql_runner")

SCRIPTS: list[str] = [
    "01_schema.sql",
    "02_data_quality.sql",
    "03_cleaning.sql",
    "04_account_panel.sql",
    "05_transitions.sql",
    "06_roll_rates.sql",
    "07_vintage_analysis.sql",
    "08_cure_rates.sql",
    "09_ageing_snapshot.sql",
    "10_segmentation.sql",
]

_SLOT = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def _sql_str(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _values(rows: list[tuple[Any, ...]]) -> str:
    return ", ".join("(" + ", ".join(_sql_str(v) for v in r) + ")" for r in rows)


def template_context(
    params: dict[str, Any] | None = None, excluded_ids: list[tuple[int, str]] | None = None
) -> dict[str, str]:
    """Build the template slot values from configuration."""
    p = params or load_params()
    mapping = p.get("STATE_MAPPING", "evidence_based")
    if mapping != "evidence_based":
        raise ValueError(
            "STATE_MAPPING=source_literal is a sensitivity view only (see docs/decisions.md "
            "D-005); the analytical pipeline runs on evidence_based."
        )
    kv = [
        ("STATE_MAPPING", mapping),
        ("MIN_N_ROW", str(p["min_n_row"])),
        ("WARN_N_ROW", str(p["warn_n_row"])),
        ("SEED", str(p["seed"])),
    ]
    excl = excluded_ids or []
    return {
        "CONFIG_VALUES": _values(kv),
        "MOB_BANDS_VALUES": _values(
            [(i, b["label"], b["lo"], b["hi"]) for i, b in enumerate(p["mob_bands"])]
        ),
        "AGE_BANDS_VALUES": _values(
            [(i, b["label"], float(b["lo"]), float(b["hi"])) for i, b in enumerate(p["age_bands"])]
        ),
        "PERIODS_VALUES": _values(
            [(i, b["name"], b["start"], b["end"]) for i, b in enumerate(p["periods"])]
        ),
        "EXCLUDED_IDS_VALUES": _values(excl) if excl else "(NULL::BIGINT, NULL::VARCHAR)",
        "SHORT_HISTORY_MONTHS": str(p["dq"]["short_history_months"]),
        "CURE_MAX_H": str(max(p["cure"]["horizons"])),
        "CURE_HORIZONS_VALUES": _values([(k,) for k in p["cure"]["horizons"]]),
        "EXCLUDE_LEFT_CENSORED": "TRUE" if p["cure"]["exclude_left_censored"] else "FALSE",
        "SEG_HORIZON": str(p["segments"]["horizon_mob"]),
        "SEG_MIN_CLIENTS": str(p["segments"]["min_clients"]),
        "SEG_MIN_EVENTS": str(p["segments"]["min_events"]),
    }


def render(sql: str, context: dict[str, str]) -> str:
    """Fill ``{{NAME}}`` slots; raise on any slot without a value."""

    def sub(m: re.Match[str]) -> str:
        key = m.group(1)
        if key not in context:
            raise KeyError(f"SQL template slot {{{{{key}}}}} has no value")
        return context[key]

    return _SLOT.sub(sub, sql)


def run_script(con: duckdb.DuckDBPyConnection, name: str, context: dict[str, str]) -> float:
    """Execute one script; return its wall time in seconds."""
    path: Path = SQL_DIR / name
    sql = render(path.read_text(encoding="utf-8"), context)
    t0 = time.perf_counter()
    con.execute(sql)
    dt = time.perf_counter() - t0
    log.info("sql %-26s %.2fs", name, dt)
    return dt


def run_scripts(
    con: duckdb.DuckDBPyConnection, names: list[str], context: dict[str, str]
) -> dict[str, float]:
    """Execute scripts in order and return timings."""
    return {n: run_script(con, n, context) for n in names}


def set_excluded_ids(con: duckdb.DuckDBPyConnection, excluded: list[tuple[int, str]]) -> None:
    """Replace ``config_excluded_ids`` after the truncation test has run."""
    con.execute("DELETE FROM config_excluded_ids")
    for cid, reason in excluded:
        con.execute("INSERT INTO config_excluded_ids VALUES (?, ?)", [int(cid), reason])


def fetch(con: duckdb.DuckDBPyConnection, table: str) -> pd.DataFrame:
    """Read a whole SQL table into pandas."""
    return con.execute(f"SELECT * FROM {table}").df()


def metrics_dict(con: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """``dq_metrics`` as a plain dict (NULL becomes NaN)."""
    df = fetch(con, "dq_metrics")
    return {
        r.metric: (float(r.value) if pd.notna(r.value) else float("nan")) for r in df.itertuples()
    }
