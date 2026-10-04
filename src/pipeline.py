"""End-to-end build: raw files -> DuckDB SQL layer -> analytics, models, bootstrap, stress
-> aggregated cubes, ``reports/results.json``, ``reports/dq_report.json`` and generated docs.

Usage::

    python -m src.pipeline --stage audit   # SQL layer + data-quality report + audit docs
    python -m src.pipeline --stage all     # everything (what `make build` runs)

Client-level tables never leave DuckDB / memory. Only aggregated cubes (no ID column,
segment cells below the suppression threshold blanked) are written to
``data/processed/cubes/``.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

import numpy as np
import pandas as pd

from src import reporting
from src.analytics import cure_rates, roll_rates, segmentation, vintage
from src.data import feature_engineering as fe
from src.data import ingestion, validation
from src.data import sql_runner as sr
from src.models import absorbing, backtesting, bootstrap, markov, mob_transition
from src.models.markov import CO_IDX, IDX, N_STATES, N_TRANSIENT
from src.stress import expected_loss, forecasting, scenarios
from src.utils import constants as C
from src.utils.helpers import (
    CUBES_DIR,
    DQ_REPORT_PATH,
    PROCESSED_DIR,
    RESULTS_PATH,
    VALIDATION_DIR,
    ensure_dirs,
    load_params,
    timed,
    vintage_qtr_label,
    write_json,
    write_parquet,
)
from src.utils.logging import get_logger

log = get_logger("pipeline")

BUCKETS = [C.B0, C.B1, C.B2, C.B3, C.B4]
PREV_METRICS = {"30+": 1, "60+": 2, "90+": 3, "CHARGE-OFF": 4}


def _ci(samples: np.ndarray, level: float = 0.95) -> tuple[float, float, float, bool]:
    """(lo, hi, se, degenerate) of a 1-D replicate array (NaN-safe)."""
    s = bootstrap.summarise(np.asarray(samples, dtype=float)[:, None], level)
    return float(s["lo"][0]), float(s["hi"][0]), float(s["se"][0]), bool(s["degenerate"][0])


def _rate(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    num = np.asarray(num, dtype=float)
    den = np.asarray(den, dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


class Build:
    """State shared by the build steps."""

    def __init__(self, params: dict[str, Any]) -> None:
        self.p = params
        self.level = float(params["bootstrap"]["ci_level"])
        self.res: dict[str, Any] = {"display": {}}
        self.dq: dict[str, Any] = {}
        self.cubes: dict[str, pd.DataFrame] = {}
        self.timings: dict[str, float] = {}

    # ------------------------------------------------------------------ display
    def show(self, key: str, value: Any, fmt: str, label: str = "") -> None:
        """Register a number for README / docs rendering (single source of truth)."""
        if isinstance(value, (np.floating, np.integer)):
            value = value.item()
        self.res["display"][key] = {"value": value, "fmt": fmt, "label": label}

    # ------------------------------------------------------------------ SQL
    def sql(self) -> None:
        """Locate raw data, run the SQL layer, apply the file-truncation rule."""
        t0 = time.perf_counter()
        source = ingestion.locate_raw()
        self.con = ingestion.connect(source)
        ctx = sr.template_context(self.p)
        self.timings.update(sr.run_scripts(self.con, sr.SCRIPTS[:2], ctx))
        self.m = sr.metrics_dict(self.con)
        last_id, nrows = ingestion.final_client_in_file_order(source)
        self.trunc = validation.file_truncation_test(nrows, last_id, self.m, self.p)
        excluded = []
        if self.trunc["excluded"]:
            excluded = [(int(float(last_id)), "credit_record.csv truncated at the Excel row limit")]
        sr.set_excluded_ids(self.con, excluded)
        self.timings.update(sr.run_scripts(self.con, sr.SCRIPTS[2:], ctx))
        self.excluded = excluded
        self.timings["sql_total"] = time.perf_counter() - t0

    def q(self, sql: str) -> pd.DataFrame:
        """Run a read-only query against the build database."""
        return self.con.execute(sql).df()

    # ------------------------------------------------------------------ audit
    def audit(self) -> None:
        """Data-quality report, pilot reconciliation and status-semantics evidence."""
        m = self.m
        conflicting = float(
            self.q("SELECT COUNT(*) c FROM app_dedup WHERE IS_DUPLICATE_ID AND HAS_CONFLICT").c[0]
        )
        vsizes = (
            self.q("SELECT OPEN_MONTH, COUNT(*) n FROM vintage_clients GROUP BY 1")
            .set_index("OPEN_MONTH")
            .n
        )
        immature = int((vsizes.index > -12).sum())
        mob0 = self.q("SELECT * FROM vintage_mob0_mix")
        lt = vintage.left_truncation_test(
            mob0, vsizes, n_first=3, tol_pp=float(self.p["vintage"]["left_truncation_tolerance_pp"])
        )
        dormant_return = m["exiting_clients_who_reenter"] / m["active_to_x_clients"]
        extra = {
            "conflicting_dup_ids": conflicting,
            "immature_vintages": immature,
            "dormant_return_share": dormant_return,
            "truncation": self.trunc,
            "left_truncation": lt,
        }
        checks = validation.dq_checks(m, extra, self.p)
        newco = self.q("SELECT * FROM dq_new_chargeoffs ORDER BY ORIGIN")
        computed = dict(m)
        row12 = newco[newco.ORIGIN == -12]
        if len(row12):
            computed["new_co_12m_from_m12"] = float(row12.new_co_12m.iloc[0])
            computed["open_0_4_at_m12"] = float(row12.open_0_4.iloc[0])
        computed["vintage_m60_clients"] = float(vsizes.get(-60, 0))
        pilot = validation.reconcile_pilot(computed, self.p)
        raw_tc = self.q("SELECT * FROM dq_raw_transition_counts")
        anomalies = self.q(
            "SELECT FROM_STATE, TO_STATE, COUNT(*) n FROM transition_anomalies GROUP BY ALL ORDER BY n DESC"
        )
        stays = self.q("SELECT * FROM absorbing_stays")
        self.dq = {
            "metrics": m,
            "checks": checks,
            "truncation": self.trunc,
            "left_truncation": lt,
            "excluded_clients": len(self.excluded),
            "conflicting_duplicate_ids": conflicting,
            "immature_vintages": immature,
            "dormant_return_share": dormant_return,
            "pilot_reconciliation": pilot,
            "new_chargeoffs": newco.to_dict("records"),
            "raw_transition_counts": raw_tc.to_dict("records"),
            "status_counts": self.q("SELECT * FROM dq_status_counts ORDER BY STATUS").to_dict(
                "records"
            ),
            "status_month0": self.q("SELECT * FROM dq_status_month0 ORDER BY STATUS").to_dict(
                "records"
            ),
            "app_nulls": self.q("SELECT * FROM dq_app_nulls").to_dict("records"),
            "transition_anomalies": anomalies.to_dict("records"),
            "absorbing_stays": stays.to_dict("records"),
            "vintage_sizes": {int(k): int(v) for k, v in vsizes.items()},
            "status_summary": {
                c["status"]: sum(1 for x in checks if x["status"] == c["status"]) for c in checks
            },
            "timings_sql": self.timings,
        }
        write_json(DQ_REPORT_PATH, self.dq)
        reporting.write_audit_docs(self.dq, self.p)
        log.info("data-quality report written (%d checks)", len(checks))

    # ------------------------------------------------------------------ frames
    def load_frames(self) -> None:
        """Pull the client-level inputs of the bootstrap from DuckDB (kept in memory only)."""
        self.panel = self.q("SELECT ID, MONTHS_BALANCE, STATE FROM panel WHERE IS_OPENED")
        self.trans = self.q(
            "SELECT ID, ORIGIN_MONTH, DEST_MONTH, FROM_STATE, TO_STATE, MOB, MOB_BAND, AGE_BAND, INCOME_BAND "
            "FROM transitions"
        )
        self.episodes = self.q(
            "SELECT ID, GRP, ENTRY_MONTH, EVENT_TYPE, EVENT_J FROM cure_episode_groups"
        )
        self.vint = self.q("SELECT * FROM vintage_clients")
        segc = self.q("SELECT * FROM segment_client_stats")
        labels = fe.seg_label_list(self.p)
        idx = {lab: i for i, lab in enumerate(labels)}
        parts = []
        for col, prefix in (("AGE_BAND", "age_band:"), ("INCOME_BAND", "income_band:")):
            sub = segc[segc[col].notna()].copy()
            sub["SEG_INDEX"] = sub[col].map(lambda v, p=prefix: idx[p + v])
            parts.append(sub)
        self.segc = pd.concat(parts, ignore_index=True)
        self.clients = np.sort(self.q("SELECT ID FROM opened_clients").ID.to_numpy())

    # ------------------------------------------------------------------ bootstrap
    def run_bootstrap(self) -> None:
        """Build client statistics and compute point and replicate column sums."""
        bt = self.p["backtest"]
        self.origins = backtesting.valid_origins(bt)
        self.pairs = [(t0, h) for t0 in self.origins for h in bt["horizons"] if t0 + h <= 0]
        with timed("client statistics"):
            self.reg = fe.build_client_stats(
                self.clients,
                self.panel,
                self.trans,
                self.episodes,
                self.vint,
                self.segc,
                self.p,
                self.pairs,
                self.origins,
            )
            S = self.reg.matrix()
        b = self.p["bootstrap"]
        t0 = time.perf_counter()
        self.R0 = bootstrap.point(S)
        self.RB = bootstrap.run(S, int(b["B"]), int(self.p["seed"]), int(b["chunk"]))
        self.timings["bootstrap"] = time.perf_counter() - t0
        self.res["bootstrap"] = {
            "B": int(b["B"]),
            "seed": int(self.p["seed"]),
            "clients": int(len(self.clients)),
            "statistics": int(S.shape[1]),
            "nonzeros": int(S.nnz),
            "runtime_s": round(self.timings["bootstrap"], 1),
            "unit": "client (ID); whole histories resampled",
        }
        self.show("boot_B", int(b["B"]), "int", "bootstrap replicates")
        self.show("boot_clients", int(len(self.clients)), "int", "clients resampled")
        # Reconciliation: unit-weight statistics equal the SQL counts.
        sql_counts = roll_rates.counts_from_long(
            self.q("SELECT FROM_STATE, TO_STATE, n FROM roll_counts WHERE SLICE_TYPE = 'overall'")
        )
        stat_counts = self.take("trans_dm", point=True)[0].sum(axis=0)
        self.res["reconciliation"] = {
            "sql_vs_client_stats_transition_counts_equal": bool(
                np.array_equal(sql_counts, stat_counts)
            ),
            "transitions": float(sql_counts.sum()),
        }
        if not self.res["reconciliation"]["sql_vs_client_stats_transition_counts_equal"]:
            raise RuntimeError("client statistics do not reconcile with SQL transition counts")

    def take(self, name: str, point: bool = False) -> np.ndarray:
        """Block of replicate (or point) sums."""
        return self.reg.take(self.R0 if point else self.RB, name)

    # ------------------------------------------------------------------ roll rates
    def roll_rates(self) -> None:
        """Matrices (views A and B) and named metrics with bootstrap intervals."""
        min_n, warn_n = int(self.p["min_n_row"]), int(self.p["warn_n_row"])
        dm0, dmb = self.take("trans_dm", True), self.take("trans_dm")
        slices: list[tuple[str, str, np.ndarray, np.ndarray | None]] = []
        slices.append(("overall", "All", dm0.sum(1)[0], dmb.sum(1)))
        for per in self.p["periods"]:
            lo, hi = per["start"] + 1 + 59, per["end"] + 1 + 59  # destination-month indices
            slices.append(
                ("period", per["name"], dm0[0, lo : hi + 1].sum(0), dmb[:, lo : hi + 1].sum(1))
            )
        b0, bb = self.take("trans_band", True), self.take("trans_band")
        for i, band in enumerate(self.p["mob_bands"]):
            slices.append(("mob_band", band["label"], b0[0, i], bb[:, i]))
        s0, sb = self.take("trans_seg", True), self.take("trans_seg")
        for i, key in enumerate(fe.seg_label_list(self.p)):
            st, lab = key.split(":", 1)
            slices.append((st, lab, s0[0, i], sb[:, i]))
        vq = self.q(
            "SELECT SLICE, FROM_STATE, TO_STATE, n FROM roll_counts WHERE SLICE_TYPE = 'vintage_qtr'"
        )
        for q, g in vq.groupby("SLICE"):
            slices.append(
                ("vintage_qtr", vintage_qtr_label(int(q)), roll_rates.counts_from_long(g), None)
            )
        self.slice_counts = {(a, b): (c, d) for a, b, c, d in slices}

        mats, named = [], []
        suppress_n = int(self.p["suppress_cube_n"])
        for st, sl, pc, bc in slices:
            for view in ("A", "B"):
                t = roll_rates.matrix_table(pc, bc, view, min_n, warn_n, self.level)
                t.insert(0, "VIEW", view)
                t.insert(0, "SLICE", sl)
                t.insert(0, "SLICE_TYPE", st)
                if st in ("age_band", "income_band"):
                    small = t.n < suppress_n
                    t.loc[small, ["n", "p", "lo", "hi", "se"]] = np.nan
                    t["cell_suppressed"] = small
                else:
                    t["cell_suppressed"] = False
                mats.append(t)
            pn = roll_rates.named_metrics(pc)
            bn = roll_rates.named_metrics(bc) if bc is not None else None
            for name, (num, den) in pn.items():
                rate = float(_rate(num, den))
                row = {
                    "SLICE_TYPE": st,
                    "SLICE": sl,
                    "METRIC": name,
                    "num": float(num),
                    "den": float(den),
                    "rate": rate,
                    "lo": np.nan,
                    "hi": np.nan,
                    "se": np.nan,
                    "degenerate": False,
                }
                if bn is not None:
                    lo, hi, se, dg = _ci(_rate(*bn[name]), self.level)
                    row.update(lo=lo, hi=hi, se=se, degenerate=dg)
                if st in ("age_band", "income_band") and 0 < num < suppress_n:
                    row.update(num=np.nan, rate=np.nan, lo=np.nan, hi=np.nan, se=np.nan)
                named.append(row)
        self.cubes["roll_matrices"] = pd.concat(mats, ignore_index=True)
        self.cubes["named_rolls"] = pd.DataFrame(named)
        nr = self.cubes["named_rolls"].set_index(["SLICE_TYPE", "SLICE", "METRIC"])
        ov = nr.loc[("overall", "All")]
        for key, metric, label in (
            ("cure_30p", "cure_30p", "one-step cure from 30-149 DPD"),
            ("forward_b0", f"forward_{C.B0}", "1-29 forward roll"),
            ("forward_b1", f"forward_{C.B1}", "30-59 forward roll"),
            ("severe_roll", "severe_roll_60_89_to_90p", "60-89 to 90+ roll"),
            ("roll_90p_co", "roll_90p_to_co", "90+ to charge-off"),
            ("persist_b0", f"persistence_{C.B0}", "1-29 persistence"),
        ):
            r = ov.loc[metric]
            self.show(f"{key}", r.rate, "pct1", label)
            self.show(f"{key}_lo", r.lo, "pct1")
            self.show(f"{key}_hi", r.hi, "pct1")
            self.show(f"{key}_n", r.den, "int")
        self.show("transitions_n", float(dm0.sum()), "int", "monthly transitions in matrices")
        # Source-literal sensitivity.
        lit = roll_rates.literal_sensitivity(self.q("SELECT * FROM dq_raw_transition_counts"))
        lm = lit["matrix"].reset_index().melt(id_vars="index", var_name="TO_STATE", value_name="p")
        lc = lit["counts"].reset_index().melt(id_vars="index", var_name="TO_STATE", value_name="n")
        lm = lm.rename(columns={"index": "FROM_STATE"}).merge(
            lc.rename(columns={"index": "FROM_STATE"}), on=["FROM_STATE", "TO_STATE"]
        )
        self.cubes["literal_sensitivity"] = lm
        stock0 = self.q(
            "SELECT RAW_STATUS, COUNT(*) n FROM panel WHERE MONTHS_BALANCE = 0 GROUP BY 1"
        )
        s0 = dict(zip(stock0.RAW_STATUS, stock0.n, strict=True))
        lit_current_share = s0.get("C", 0) / sum(v for k, v in s0.items() if k != "X")
        ev_b0_share = s0.get("0", 0) / sum(
            v for k, v in s0.items() if k in {"0", "1", "2", "3", "4", "5"}
        )
        self.res["literal_sensitivity"] = {
            "current_persistence": lit["current_persistence"],
            "current_deterioration": lit["current_deterioration"],
            "current_row_n": lit["current_row_n"],
            "literal_current_share_m0": lit_current_share,
            "evidence_b0_share_of_open_m0": ev_b0_share,
        }
        self.show(
            "lit_current_persist",
            lit["current_persistence"],
            "pct2",
            "CURRENT persistence (literal)",
        )
        self.show(
            "lit_current_det",
            lit["current_deterioration"],
            "pct3",
            "CURRENT deterioration (literal)",
        )
        self.show("lit_current_share", lit_current_share, "pct1", "CURRENT share at M0 (literal)")

    # ------------------------------------------------------------------ prevalence and risk signal
    def prevalence(self) -> None:
        """30+/60+/90+/charge-off share of open accounts by month with intervals."""
        p0, pb = self.take("prevalence", True)[0], self.take("prevalence")
        rows = []
        for mi in range(61):
            den0 = p0[mi, 0]
            for name, k in PREV_METRICS.items():
                rate = float(_rate(p0[mi, k], den0))
                lo, hi, se, dg = _ci(_rate(pb[:, mi, k], pb[:, mi, 0]), self.level)
                rows.append(
                    {
                        "MONTHS_BALANCE": mi - 60,
                        "METRIC": name,
                        "num": float(p0[mi, k]),
                        "den": float(den0),
                        "rate": rate,
                        "lo": lo,
                        "hi": hi,
                        "se": se,
                        "degenerate": dg,
                    }
                )
            b0 = p0[mi, 0] - p0[mi, 1]
            lo, hi, se, dg = _ci(_rate(pb[:, mi, 0] - pb[:, mi, 1], pb[:, mi, 0]), self.level)
            rows.append(
                {
                    "MONTHS_BALANCE": mi - 60,
                    "METRIC": "1-29",
                    "num": float(b0),
                    "den": float(den0),
                    "rate": float(_rate(b0, den0)),
                    "lo": lo,
                    "hi": hi,
                    "se": se,
                    "degenerate": dg,
                }
            )
        prev = pd.DataFrame(rows)
        self.cubes["prevalence"] = prev
        last = prev[prev.MONTHS_BALANCE == 0].set_index("METRIC")
        self.show("open_m0", last.loc["30+"].den, "int", "open accounts at month 0")
        for key, met in (
            ("prev30_m0", "30+"),
            ("prev60_m0", "60+"),
            ("prev90_m0", "90+"),
            ("co_m0", "CHARGE-OFF"),
        ):
            self.show(key, last.loc[met].rate, "pct2")
            self.show(f"{key}_lo", last.loc[met].lo, "pct2")
            self.show(f"{key}_hi", last.loc[met].hi, "pct2")
            self.show(f"{key}_n", last.loc[met].num, "int")

        # Risk signal: forward roll, latest 12 destination months vs prior 12, per as-of month.
        dm0, dmb = self.take("trans_dm", True)[0], self.take("trans_dm")
        min_n = int(self.p["min_n_row"])
        rows = []
        for asof in range(-36, 1):
            hi = asof + 59
            for b in BUCKETS:
                fi = IDX[b]
                worse = [
                    IDX[s]
                    for s in C.MARKOV_ORDER
                    if s in C.OPEN_STATES and C.STATE_ORDER[s] > C.STATE_ORDER[b]
                ]

                def fw(
                    arr: np.ndarray, lo_i: int, hi_i: int, fi: int = fi, worse: list[int] = worse
                ) -> tuple:
                    blk = arr[..., lo_i : hi_i + 1, fi, :].sum(axis=-2)
                    return blk[..., worse].sum(axis=-1), blk.sum(axis=-1)

                ln, ld = fw(dm0, hi - 11, hi)
                pn, pd_ = fw(dm0, hi - 23, hi - 12)
                lnb, ldb = fw(dmb, hi - 11, hi)
                pnb, pdb = fw(dmb, hi - 23, hi - 12)
                diff = float(_rate(ln, ld) - _rate(pn, pd_))
                lo, hi_, _, _ = _ci(_rate(lnb, ldb) - _rate(pnb, pdb), self.level)
                enough = ld >= min_n and pd_ >= min_n
                clear = bool(enough and np.isfinite(lo) and (lo > 0 or hi_ < 0))
                rows.append(
                    {
                        "AS_OF": asof,
                        "BUCKET": b,
                        "latest_rate": float(_rate(ln, ld)),
                        "prior_rate": float(_rate(pn, pd_)),
                        "latest_n": float(ld),
                        "prior_n": float(pd_),
                        "diff": diff,
                        "lo": lo,
                        "hi": hi_,
                        "adequate_n": bool(enough),
                        "clear": clear,
                    }
                )
        self.cubes["risk_signal"] = pd.DataFrame(rows)

    # ------------------------------------------------------------------ vintage
    def vintages(self) -> None:
        """Monthly and quarterly curves, checkpoint intervals, recent-vs-old comparison."""
        vc = self.q("SELECT * FROM vintage_curves ORDER BY VINTAGE_MONTH, MOB")
        self.cubes["vintage_monthly"] = vintage.monthly_rates(vc)
        self.cubes["vintage_quarterly"] = vintage.quarterly_curves(vc)
        self.cubes["vintage_first_delinquency"] = self.q("SELECT * FROM vintage_first_delinquency")
        self.cubes["vintage_max_severity"] = self.q("SELECT * FROM vintage_max_severity")
        ks = self.p["vintage"]["checkpoints"]
        v0, vb = self.take("vintage", True)[0], self.take("vintage")
        names = ["ever_30p", "ever_60p", "ever_90p", "ever_co"]
        rows, comp = [], []
        for ki, k in enumerate(ks):
            observable = [q for q in range(21) if min(-60 + 3 * q + 2, 0) + k <= 0]
            for q in observable:
                for j, nm in enumerate(names, start=1):
                    lo, hi, se, dg = _ci(_rate(vb[:, q, ki, j], vb[:, q, ki, 0]), self.level)
                    rows.append(
                        {
                            "VINTAGE_QTR": q,
                            "VINTAGE_LABEL": vintage_qtr_label(q),
                            "MOB": k,
                            "METRIC": nm,
                            "n_accounts": float(v0[q, ki, 0]),
                            "events": float(v0[q, ki, j]),
                            "rate": float(_rate(v0[q, ki, j], v0[q, ki, 0])),
                            "lo": lo,
                            "hi": hi,
                            "se": se,
                            "degenerate": dg,
                        }
                    )
            if len(observable) >= 8:
                old, new = observable[:4], observable[-4:]
                for j, nm in enumerate(names, start=1):
                    r_old = _rate(v0[old, ki, j].sum(), v0[old, ki, 0].sum())
                    r_new = _rate(v0[new, ki, j].sum(), v0[new, ki, 0].sum())
                    d_b = _rate(vb[:, new, ki, j].sum(1), vb[:, new, ki, 0].sum(1)) - _rate(
                        vb[:, old, ki, j].sum(1), vb[:, old, ki, 0].sum(1)
                    )
                    lo, hi, _, _ = _ci(d_b, self.level)
                    verdict = "higher" if lo > 0 else ("lower" if hi < 0 else "no clear difference")
                    comp.append(
                        {
                            "MOB": k,
                            "METRIC": nm,
                            "old_quarters": f"{vintage_qtr_label(old[0])} .. {vintage_qtr_label(old[-1])}",
                            "recent_quarters": f"{vintage_qtr_label(new[0])} .. {vintage_qtr_label(new[-1])}",
                            "old_rate": float(r_old),
                            "recent_rate": float(r_new),
                            "diff": float(r_new - r_old),
                            "lo": lo,
                            "hi": hi,
                            "verdict": verdict,
                            "old_n": float(v0[old, ki, 0].sum()),
                            "recent_n": float(v0[new, ki, 0].sum()),
                        }
                    )
        self.cubes["vintage_checkpoints"] = pd.DataFrame(rows)
        self.cubes["vintage_comparison"] = pd.DataFrame(comp)
        c12 = self.cubes["vintage_comparison"]
        r = c12[(c12.MOB == 12) & (c12.METRIC == "ever_30p")].iloc[0]
        self.show("vint_old_e30_12", r.old_rate, "pct1", "ever-30+ by MOB 12, oldest four quarters")
        self.show(
            "vint_new_e30_12",
            r.recent_rate,
            "pct1",
            "ever-30+ by MOB 12, most recent four quarters",
        )
        self.show("vint_diff_e30_12", r["diff"] * 100, "pp1")
        self.show("vint_diff_e30_12_lo", r.lo * 100, "pp1")
        self.show("vint_diff_e30_12_hi", r.hi * 100, "pp1")
        self.show("vint_verdict_e30_12", r.verdict, "text")
        r6 = c12[(c12.MOB == 12) & (c12.METRIC == "ever_60p")].iloc[0]
        self.show("vint_verdict_e60_12", r6.verdict, "text")
        self.show("vint_diff_e60_12", r6["diff"] * 100, "pp2")
        self.show("vint_diff_e60_12_lo", r6.lo * 100, "pp2")
        self.show("vint_diff_e60_12_hi", r6.hi * 100, "pp2")
        self.show("vintages_n", int(vc.VINTAGE_MONTH.nunique()), "int", "monthly vintages")

    # ------------------------------------------------------------------ cure
    def cure(self) -> None:
        """Cumulative incidence (primary), fixed-window (secondary) and raw outcome stack."""
        hz = self.p["cure"]["horizons"]
        h0, hb = self.take("cure_hazard", True)[0], self.take("cure_hazard")
        i0, ib = self.take("cure_immediate", True)[0], self.take("cure_immediate")
        f0, fb = self.take("cure_fixed", True)[0], self.take("cure_fixed")
        r0 = self.take("cure_raw", True)[0]
        c0 = cure_rates.cumulative_incidence(h0, i0)
        cb = cure_rates.cumulative_incidence(hb, ib)
        rows, raw_rows = [], []
        for g, grp in enumerate(fe.CURE_GROUPS):
            for ki, k in enumerate(hz):
                rec = {"GRP": grp, "K": k, "episodes": float(i0[g, 1])}
                for key in ("cif_cure", "cif_co", "still_30p"):
                    rec[key] = float(c0[key][g, k - 1])
                    lo, hi, se, dg = _ci(cb[key][:, g, k - 1], self.level)
                    rec.update({f"{key}_lo": lo, f"{key}_hi": hi, f"{key}_degenerate": dg})
                fw0 = cure_rates.fixed_window(f0[g, ki, 0], f0[g, ki, 1], f0[g, ki, 2])
                fwb = cure_rates.fixed_window(fb[:, g, ki, 0], fb[:, g, ki, 1], fb[:, g, ki, 2])
                rec["fw_eligible"] = float(f0[g, ki, 0])
                for key in ("cure", "co"):
                    rec[f"fw_{key}"] = float(fw0[key])
                    lo, hi, _, _ = _ci(fwb[key], self.level)
                    rec.update({f"fw_{key}_lo": lo, f"fw_{key}_hi": hi})
                rows.append(rec)
                tot = r0[g, ki, 0]
                for col, lab in enumerate(
                    ["CURED", "CHARGED-OFF", "CENSORED", "STILL 30+"], start=1
                ):
                    raw_rows.append(
                        {
                            "GRP": grp,
                            "K": k,
                            "OUTCOME": lab,
                            "n": float(r0[g, ki, col]),
                            "share": float(_rate(r0[g, ki, col], tot)),
                            "episodes": float(tot),
                        }
                    )
        cif = pd.DataFrame(rows)
        self.cubes["cure_cif"] = cif
        self.cubes["cure_raw"] = pd.DataFrame(raw_rows)
        self.cubes["cure_outcomes_sql"] = self.q("SELECT * FROM cure_outcomes ORDER BY GRP, K")
        red = self.q("SELECT * FROM cure_redelinquency").iloc[0]
        self.res["cure_redelinquency"] = {
            "cured_with_window": float(red.cured_with_window),
            "redelinquent_6m": float(red.redelinquent_6m),
            "rate": float(_rate(red.redelinquent_6m, red.cured_with_window)),
        }
        a = cif[(cif.GRP == "All episodes")].set_index("K")
        for k in (3, 6):
            self.show(
                f"cure_cif_{k}", a.loc[k].cif_cure, "pct1", f"cumulative cure within {k} months"
            )
            self.show(f"cure_cif_{k}_lo", a.loc[k].cif_cure_lo, "pct1")
            self.show(f"cure_cif_{k}_hi", a.loc[k].cif_cure_hi, "pct1")
            self.show(
                f"cure_co_{k}", a.loc[k].cif_co, "pct2", f"cumulative charge-off within {k} months"
            )
            self.show(f"cure_co_{k}_lo", a.loc[k].cif_co_lo, "pct2")
            self.show(f"cure_co_{k}_hi", a.loc[k].cif_co_hi, "pct2")
        self.show("cure_episodes", a.loc[6].episodes, "int", "30+ episodes analysed")
        e60 = cif[(cif.GRP == "Entry 60+")].set_index("K")
        e30 = cif[(cif.GRP == "Entry 30-59")].set_index("K")
        self.show("cure_e30_6", e30.loc[6].cif_cure, "pct1")
        self.show("cure_e60_6", e60.loc[6].cif_cure, "pct1")
        self.show("cure_e60_co_6", e60.loc[6].cif_co, "pct1")
        self.show("cure_e60_n", e60.loc[6].episodes, "int")
        self.show("redelinq_6m", self.res["cure_redelinquency"]["rate"], "pct1")

    # ------------------------------------------------------------------ segments
    def segments(self) -> None:
        """Segment rates with intervals and suppression."""
        sm = segmentation.point_rates(self.q("SELECT * FROM segment_metrics"))
        g0, gb = self.take("segment", True)[0], self.take("segment")
        labels = fe.seg_label_list(self.p)
        out = []
        for r in sm.itertuples(index=False):
            i = labels.index(f"{r.SEG_TYPE}:{r.SEGMENT}")
            rec = r._asdict()
            for key, (nc, dc), flag in (
                ("ever60_rate", (1, 0), r.suppress_ever60),
                ("prev30_rate", (3, 2), r.suppress_prev30),
                ("cure_rate", (5, 4), r.suppress_cure),
            ):
                lo, hi, _, _ = _ci(_rate(gb[:, i, nc], gb[:, i, dc]), self.level)
                rec[f"{key}_lo"] = np.nan if flag else lo
                rec[f"{key}_hi"] = np.nan if flag else hi
                if not flag and abs(_rate(g0[i, nc], g0[i, dc]) - getattr(r, key)) > 1e-12:
                    raise RuntimeError("segment statistics do not reconcile with SQL")
            out.append(rec)
        self.cubes["segments"] = pd.DataFrame(out)
        cov = self.q("SELECT * FROM segment_coverage").iloc[0]
        self.res["segment_coverage"] = {k: float(v) for k, v in cov.items()}
        self.show("seg_matched_opened", cov.matched_opened, "int")
        self.show("seg_opened", cov.opened_clients, "int")

    # ------------------------------------------------------------------ absorbing chain
    def absorbing_chain(self) -> None:
        """P(eventual charge-off), time to resolution and the point of no return."""
        c0, cb = self.slice_counts[("overall", "All")]
        P0, Pb = markov.estimate(c0), markov.estimate(cb)
        self.P0, self.Pb = P0, Pb
        rows, pnr = [], {}
        for view, inc in (("with_dormant", True), ("dormant_dropped", False)):
            a0 = absorbing.analyse(P0, inc)
            ab = absorbing.analyse(Pb, inc)
            for i, s in enumerate(a0.states):
                rec = {"VIEW": view, "STATE": s}
                for key, arr0, arrb in (
                    ("p_co", a0.p_chargeoff, ab.p_chargeoff),
                    ("p_paid", a0.p_paidoff, ab.p_paidoff),
                    ("months", a0.months_to_resolution, ab.months_to_resolution),
                ):
                    lo, hi, se, _ = _ci(arrb[:, i], self.level)
                    rec.update(
                        {key: float(arr0[i]), f"{key}_lo": lo, f"{key}_hi": hi, f"{key}_se": se}
                    )
                rows.append(rec)
            reps = absorbing.point_of_no_return_batch(ab)
            point = absorbing.point_of_no_return(a0)
            pnr[view] = {
                "bucket": point,
                "replicate_share_same": float(np.mean([r == point for r in reps])),
                "replicate_distribution": {
                    str(k): float(np.mean([r == k for r in reps])) for k in set(reps)
                },
            }
        tab = pd.DataFrame(rows)
        self.cubes["absorbing"] = tab
        self.res["absorbing"] = {"point_of_no_return": pnr}
        w = tab[tab.VIEW == "with_dormant"].set_index("STATE")
        x = tab[tab.VIEW == "dormant_dropped"].set_index("STATE")
        pb = pnr["with_dormant"]["bucket"]
        self.show("pnr_bucket", pb or "none", "text", "point of no return")
        self.show("pnr_share", pnr["with_dormant"]["replicate_share_same"], "pct0")
        self.show("pnr_bucket_x", pnr["dormant_dropped"]["bucket"] or "none", "text")
        self.show("pnr_share_x", pnr["dormant_dropped"]["replicate_share_same"], "pct0")
        if pb:
            self.show("pnr_pco", w.loc[pb].p_co, "pct1")
            self.show("pnr_pco_lo", w.loc[pb].p_co_lo, "pct1")
            self.show("pnr_pco_hi", w.loc[pb].p_co_hi, "pct1")
        for key, s in (("b0", C.B0), ("b1", C.B1), ("b2", C.B2), ("b3", C.B3), ("b4", C.B4)):
            self.show(f"pco_{key}", w.loc[s].p_co, "pct1")
            self.show(f"pco_{key}_lo", w.loc[s].p_co_lo, "pct1")
            self.show(f"pco_{key}_hi", w.loc[s].p_co_hi, "pct1")
            self.show(f"months_{key}", w.loc[s].months, "num1")
            self.show(f"pco_x_{key}", x.loc[s].p_co, "pct1")
        self.res["absorbing"]["pilot_check"] = [
            {
                "bucket": b,
                "pilot_p_co": pc,
                "computed_p_co": float(x.loc[b].p_co),
                "pilot_months": pm,
                "computed_months": float(x.loc[b].months),
            }
            for b, pc, pm in zip(
                BUCKETS,
                self.p["pilot_targets"]["chain_x_dropped_p_co"],
                self.p["pilot_targets"]["chain_x_dropped_months"],
                strict=True,
            )
        ]

    # ------------------------------------------------------------------ backtest
    def backtest(self) -> None:
        """Rolling-origin backtest with baselines, skill scores and count calibration."""
        bt = self.p["backtest"]
        dm0, dmb = self.take("trans_dm", True), self.take("trans_dm")
        Por0, Porb = self.P0[None], self.Pb
        rng = np.random.default_rng(int(self.p["seed"]) + 1)
        recs = []
        calib = []
        self.bt_boot: dict[tuple[int, int], dict] = {}
        for t0, h in self.pairs:
            c0, cb = self.take(f"cohort_{t0}_{h}", True), self.take(f"cohort_{t0}_{h}")
            p0, pbp = self.take(f"portfolio_{t0}", True), self.take(f"portfolio_{t0}")
            e0 = backtesting.evaluate_pair(dm0, c0, p0, t0, h, int(bt["rolling_window"]), Por0)
            eb = backtesting.evaluate_pair(dmb, cb, pbp, t0, h, int(bt["rolling_window"]), Porb)
            self.bt_boot[(t0, h)] = eb
            for model, mets in e0.items():
                if model == "_meta":
                    continue
                for met, v in mets.items():
                    lo, hi, se, _ = _ci(eb[model][met], self.level)
                    recs.append(
                        {
                            "origin": t0,
                            "horizon": h,
                            "model": model,
                            "metric": met,
                            "value": float(v[0]),
                            "lo": lo,
                            "hi": hi,
                            "se": se,
                        }
                    )
            for base in ("persistence", "static_mix"):
                for met in (
                    "mae_pp",
                    "rmse_pp",
                    "max_abs_pp",
                    "err_30p_pp",
                    "err_60p_pp",
                    "err_90p_pp",
                    "err_co_pp",
                ):
                    sk0 = backtesting.skill(e0["markov"][met], e0[base][met])
                    skb = backtesting.skill(eb["markov"][met], eb[base][met])
                    lo, hi, se, _ = _ci(skb, self.level)
                    recs.append(
                        {
                            "origin": t0,
                            "horizon": h,
                            "model": f"skill_vs_{base}",
                            "metric": met,
                            "value": float(sk0[0]),
                            "lo": lo,
                            "hi": hi,
                            "se": se,
                        }
                    )
            meta = {k: float(v[0]) for k, v in e0["_meta"].items()}
            n_obs = int(round(meta["observed_n"]))
            p_rep = eb["markov"]["forecast_co_share"]
            sims = rng.binomial(n_obs, np.clip(np.nan_to_num(p_rep), 0, 1))
            lo, hi = np.quantile(sims, [(1 - self.level) / 2, 1 - (1 - self.level) / 2])
            calib.append(
                {
                    "origin": t0,
                    "horizon": h,
                    "cohort_n": meta["cohort_n"],
                    "observed_n": meta["observed_n"],
                    "missing_n": meta["missing_n"],
                    "predicted_co": meta["pred_co_markov"],
                    "actual_co": meta["actual_co"],
                    "pred_lo": float(lo),
                    "pred_hi": float(hi),
                    "inside": bool(lo <= meta["actual_co"] <= hi),
                }
            )
            for s in C.MARKOV_ORDER:
                recs.append(
                    {
                        "origin": t0,
                        "horizon": h,
                        "model": "markov",
                        "metric": f"forecast_share:{s}",
                        "value": meta[f"forecast_share:{s}"],
                        "lo": np.nan,
                        "hi": np.nan,
                        "se": np.nan,
                    }
                )
                recs.append(
                    {
                        "origin": t0,
                        "horizon": h,
                        "model": "actual",
                        "metric": f"actual_share:{s}",
                        "value": meta[f"actual_share:{s}"],
                        "lo": np.nan,
                        "hi": np.nan,
                        "se": np.nan,
                    }
                )
        self.bt = pd.DataFrame(recs)
        self.calib = pd.DataFrame(calib)
        self.mob_backtest()
        self.bt = pd.concat([self.bt, self.mob_bt], ignore_index=True)
        self.stationarity()
        self.history_test()
        self.summarise_backtest()

    def mob_backtest(self) -> None:
        """MOB-conditioned forecasts (point estimates) with alpha tuned on training data."""
        bt = self.p["backtest"]
        bands = self.p["mob_bands"]
        tr = self.trans.copy()
        tr["BAND"] = mob_transition.band_index(tr.MOB.to_numpy(), bands)
        tr["F"] = tr.FROM_STATE.map(IDX)
        tr["T"] = tr.TO_STATE.map(IDX)
        arr = np.zeros((len(bands), 60, N_TRANSIENT, N_STATES))
        g = tr.groupby(["BAND", "DEST_MONTH", "F", "T"]).size()
        for (b, dmon, f, t), n in g.items():
            arr[b, dmon + 59, f, t] = n
        self.band_dm = arr
        v = int(bt["smoothing_validation_months"])
        panel = self.panel
        mob = panel.merge(self.vint[["ID", "OPEN_MONTH"]], on="ID")
        mob["MOB"] = mob.MONTHS_BALANCE - mob.OPEN_MONTH
        state_at = panel.set_index(["ID", "MONTHS_BALANCE"]).STATE
        recs, alphas = [], []
        for t0, h in self.pairs:
            hi = t0 + 59
            fit_hi = hi - v
            fit_band = arr[:, : fit_hi + 1].sum(1)
            val_band = arr[:, fit_hi + 1 : hi + 1].sum(1)
            alpha, _ = mob_transition.tune_alpha(
                fit_band, fit_band.sum(0), val_band, bt["dirichlet_alpha_grid"]
            )
            alphas.append({"origin": t0, "horizon": h, "alpha": alpha})
            train = arr[:, : hi + 1].sum(1)
            bandP = mob_transition.smoothed_band_matrices(train, train.sum(0), alpha)
            coh = mob[(t0 == mob.MONTHS_BALANCE) & mob.STATE.isin(C.TRANSIENT)]
            cbm = np.zeros((61, N_TRANSIENT))
            for (mm, s), n in coh.groupby(["MOB", "STATE"]).size().items():
                cbm[int(mm), IDX[s]] = n
            fc = mob_transition.mob_forecast(cbm, bandP, h, bands)
            end = state_at.reindex(list(zip(coh.ID, coh.MONTHS_BALANCE + h, strict=True))).dropna()
            act = np.zeros(N_STATES)
            for s, n in end.value_counts().items():
                act[IDX[s]] = n
            fcs, acs = fc / fc.sum(), act / act.sum()
            for met, val in backtesting.errors(fcs[None], acs[None]).items():
                recs.append(
                    {
                        "origin": t0,
                        "horizon": h,
                        "model": "mob_conditioned",
                        "metric": met,
                        "value": float(val[0]),
                        "lo": np.nan,
                        "hi": np.nan,
                        "se": np.nan,
                    }
                )
        self.mob_bt = pd.DataFrame(recs)
        self.res["mob_alpha"] = alphas
        full = arr.sum(1)
        self.cubes["mob_homogeneity"] = pd.DataFrame(
            mob_transition.homogeneity_tests(full, [b["label"] for b in bands])
        )
        # Key probability differences between bands (mature minus early) with intervals.
        b0, bb = self.take("trans_band", True)[0], self.take("trans_band")
        P0, Pb = markov.estimate(b0), markov.estimate(bb)
        diffs = []
        for f, t in (
            (C.B0, C.B1),
            (C.B0, C.PAID_OFF),
            (C.B0, C.DORMANT),
            (C.B1, C.B0),
            (C.B1, C.B2),
            (C.B2, C.B3),
        ):
            for bi, band in enumerate(bands):
                lo, hi_, _, _ = _ci(Pb[:, bi, IDX[f], IDX[t]], self.level)
                diffs.append(
                    {
                        "FROM_STATE": f,
                        "TO_STATE": t,
                        "band": band["label"],
                        "p": float(P0[bi, IDX[f], IDX[t]]),
                        "lo": lo,
                        "hi": hi_,
                        "row_n": float(b0[bi, IDX[f]].sum()),
                    }
                )
            d = Pb[:, -1, IDX[f], IDX[t]] - Pb[:, 0, IDX[f], IDX[t]]
            lo, hi_, _, _ = _ci(d, self.level)
            diffs.append(
                {
                    "FROM_STATE": f,
                    "TO_STATE": t,
                    "band": "mature minus early",
                    "p": float(P0[-1, IDX[f], IDX[t]] - P0[0, IDX[f], IDX[t]]),
                    "lo": lo,
                    "hi": hi_,
                    "row_n": np.nan,
                }
            )
        self.cubes["mob_band_probabilities"] = pd.DataFrame(diffs)

    def stationarity(self) -> None:
        """First half vs second half of the window: chi-square per row and out-of-time error."""
        dm = self.take("trans_dm", True)[0]
        first = dm[:30].sum(0)  # destination -59..-30 (origin -60..-31)
        second = dm[30:].sum(0)  # destination -29..0 (origin -30..-1)
        tests = pd.DataFrame(mob_transition.two_sample_tests(first, second))
        P1, P2 = markov.estimate(first), markov.estimate(second)
        tv = 0.5 * np.abs(P1[:N_TRANSIENT] - P2[:N_TRANSIENT]).sum(axis=1)
        tests["total_variation"] = tv
        self.cubes["stationarity"] = tests
        # Out-of-time: 12-month forecast from origin -12 using the first-half matrix vs the
        # expanding matrix available at -12.
        c = self.take("cohort_-12_12", True)[0]
        full_mix = c.sum(-1)
        pi = np.zeros(N_STATES)
        pi[:N_TRANSIENT] = full_mix
        act = c[:, :N_STATES].sum(0)
        act = act / act.sum()
        P_exp = markov.estimate(backtesting.training_counts(dm[None], -12))[0]
        out = {}
        for name, P in (("first_half", P1), ("expanding_to_m12", P_exp)):
            fc = markov.forecast(pi, P, 12)
            out[name] = float(backtesting.errors((fc / fc.sum())[None], act[None])["mae_pp"][0])
        self.res["stationarity"] = {
            "rows_rejecting_at_5pct": int((tests.p_value < 0.05).sum()),
            "rows_tested": int(tests.p_value.notna().sum()),
            "oot_mae_pp_origin_m12_h12": out,
        }

    def history_test(self) -> None:
        """Anderson-Goodman test of first-order vs second-order dependence for 30+ origins."""
        tri = self.q("SELECT * FROM transition_triples")
        d = {
            (r.PREV_STATE, r.CUR_STATE, r.NEXT_STATE): float(r.n)
            for r in tri.itertuples(index=False)
        }
        self.cubes["history_test"] = pd.DataFrame(
            mob_transition.anderson_goodman(d, [C.B1, C.B2, C.B3, C.B4])
        )

    def summarise_backtest(self) -> None:
        """Headline backtest numbers: latest origin per horizon and the average across origins."""
        bt = self.bt
        heads = {}
        for h in self.p["backtest"]["horizons"]:
            sub = bt[bt.horizon == h]
            latest = int(sub.origin.max())
            hd = {"latest_origin": latest, "n_origins": int(sub.origin.nunique())}
            for model in (
                "markov",
                "markov_rolling",
                "persistence",
                "static_mix",
                "oracle",
                "mob_conditioned",
            ):
                for met in (
                    "mae_pp",
                    "rmse_pp",
                    "err_co_pp",
                    "err_30p_pp",
                    "err_60p_pp",
                    "err_90p_pp",
                ):
                    s = sub[(sub.model == model) & (sub.metric == met)]
                    if s.empty:
                        continue
                    lr = s[s.origin == latest].iloc[0]
                    hd[f"{model}:{met}:latest"] = float(lr.value)
                    hd[f"{model}:{met}:latest_lo"] = float(lr.lo)
                    hd[f"{model}:{met}:latest_hi"] = float(lr.hi)
                    hd[f"{model}:{met}:mean_abs"] = float(s.value.abs().mean())
            for base in ("persistence", "static_mix"):
                s = sub[(sub.model == f"skill_vs_{base}") & (sub.metric == "mae_pp")]
                lr = s[s.origin == latest].iloc[0]
                hd[f"skill_vs_{base}:mae:latest"] = float(lr.value)
                hd[f"skill_vs_{base}:mae:latest_lo"] = float(lr.lo)
                hd[f"skill_vs_{base}:mae:latest_hi"] = float(lr.hi)
                mk = (
                    sub[(sub.model == "markov") & (sub.metric == "mae_pp")]
                    .set_index("origin")
                    .value
                )
                bs = sub[(sub.model == base) & (sub.metric == "mae_pp")].set_index("origin").value
                hd[f"skill_vs_{base}:mae:avg"] = float(1 - mk.mean() / bs.mean())
                hd[f"wins_vs_{base}:mae"] = int((mk < bs).sum())
            heads[h] = hd
        cal = self.calib
        self.res["backtest"] = {
            "origins": self.origins,
            "pairs": len(self.pairs),
            "headline": heads,
            "calibration_inside": int(cal.inside.sum()),
            "calibration_pairs": len(cal),
            "missing_share_mean": float((cal.missing_n / cal.cohort_n).mean()),
        }
        h12 = heads[12]
        self.show("bt_pairs", len(self.pairs), "int", "origin x horizon pairs")
        self.show("bt_origins", len(self.origins), "int")
        self.show("bt_latest_12", h12["latest_origin"], "int")
        self.show("bt_mae_markov_12", h12["markov:mae_pp:latest"], "num2")
        self.show("bt_mae_markov_12_lo", h12["markov:mae_pp:latest_lo"], "num2")
        self.show("bt_mae_markov_12_hi", h12["markov:mae_pp:latest_hi"], "num2")
        self.show("bt_mae_persist_12", h12["persistence:mae_pp:latest"], "num2")
        self.show("bt_mae_static_12", h12["static_mix:mae_pp:latest"], "num2")
        self.show("bt_skill_persist_12", h12["skill_vs_persistence:mae:latest"], "num2")
        self.show("bt_skill_persist_12_lo", h12["skill_vs_persistence:mae:latest_lo"], "num2")
        self.show("bt_skill_persist_12_hi", h12["skill_vs_persistence:mae:latest_hi"], "num2")
        self.show("bt_skill_static_12", h12["skill_vs_static_mix:mae:latest"], "num2")
        self.show("bt_skill_static_12_lo", h12["skill_vs_static_mix:mae:latest_lo"], "num2")
        self.show("bt_skill_static_12_hi", h12["skill_vs_static_mix:mae:latest_hi"], "num2")
        self.show("bt_wins_static_12", h12["wins_vs_static_mix:mae"], "int")
        self.show("bt_skill_static_avg_12", h12["skill_vs_static_mix:mae:avg"], "num2")
        self.show("bt_skill_persist_avg_12", h12["skill_vs_persistence:mae:avg"], "num2")
        self.show("bt_wins_persist_12", h12["wins_vs_persistence:mae"], "int")
        self.show("bt_n_origins_12", h12["n_origins"], "int")
        self.show("bt_mae_mob_12", h12.get("mob_conditioned:mae_pp:latest", np.nan), "num2")
        self.show("bt_mae_markov_avg_12", h12["markov:mae_pp:mean_abs"], "num2")
        self.show("bt_mae_mob_avg_12", h12.get("mob_conditioned:mae_pp:mean_abs", np.nan), "num2")
        self.show("bt_mae_rolling_avg_12", h12["markov_rolling:mae_pp:mean_abs"], "num2")
        lc = cal[(cal.horizon == 12) & (cal.origin == h12["latest_origin"])].iloc[0]
        self.show(
            "cal_pred_12", lc.predicted_co, "num1", "predicted charge-offs, latest 12M origin"
        )
        self.show("cal_act_12", lc.actual_co, "int", "observed charge-offs, latest 12M origin")
        self.show("cal_lo_12", lc.pred_lo, "int")
        self.show("cal_hi_12", lc.pred_hi, "int")
        self.show("cal_inside", int(cal.inside.sum()), "int")
        self.show("cal_pairs", len(cal), "int")
        st = self.res["stationarity"]
        self.show("stat_reject", st["rows_rejecting_at_5pct"], "int")
        self.show("stat_rows", st["rows_tested"], "int")
        mh = self.cubes["mob_homogeneity"]
        self.show("mob_reject", int((mh.p_value < 0.05).sum()), "int")
        self.show("mob_rows", int(mh.p_value.notna().sum()), "int")

    # ------------------------------------------------------------------ stress
    def stress(self) -> None:
        """Scenario EL with intervals, reverse stress, sensitivities, live-app replicates."""
        sp = self.p["stress"]
        ead, lgd = float(sp["ead"]), float(sp["lgd"])
        coh0 = self.take("cohort_m0", True)[0]
        cohb = self.take("cohort_m0")
        self.coh0 = coh0
        presets = scenarios.preset_parameters(self.p)
        rows = []
        base0, baseb = {}, {}
        for name, (m, c) in presets.items():
            for h in sp["horizons"]:
                el0 = float(expected_loss.scenario_el(self.P0, coh0, h, m, c, ead, lgd))
                elb = expected_loss.scenario_el(self.Pb, cohb, h, m, c, ead, lgd)
                if name == "BASE":
                    base0[h], baseb[h] = el0, elb
                lo, hi, se, _ = _ci(elb, self.level)
                inc_b = elb - baseb[h]
                upl_b = _rate(inc_b, baseb[h])
                ilo, ihi, _, _ = _ci(inc_b, self.level)
                ulo, uhi, _, _ = _ci(upl_b, self.level)
                rows.append(
                    {
                        "scenario": name,
                        "m": m,
                        "c": c,
                        "horizon": h,
                        "el": el0,
                        "el_lo": lo,
                        "el_hi": hi,
                        "el_se": se,
                        "incremental": el0 - base0[h],
                        "incremental_lo": ilo,
                        "incremental_hi": ihi,
                        "uplift": float(_rate(el0 - base0[h], base0[h])),
                        "uplift_lo": ulo,
                        "uplift_hi": uhi,
                        "expected_chargeoffs": el0 / (ead * lgd),
                    }
                )
        tab = pd.DataFrame(rows)
        self.cubes["stress_presets"] = tab
        contrib = []
        for name, (m, c) in presets.items():
            for h in sp["horizons"]:
                cs = expected_loss.expected_loss(
                    scenarios.stress_matrix(self.P0, m, c), coh0, h, ead, lgd
                )
                for s, v in zip(C.TRANSIENT, cs, strict=True):
                    contrib.append(
                        {
                            "scenario": name,
                            "horizon": h,
                            "STATE": s,
                            "n": float(coh0[IDX[s]]),
                            "contribution": float(v),
                        }
                    )
        self.cubes["stress_contributions"] = pd.DataFrame(contrib)
        target = float(sp["reverse_target_multiple"])
        m_up = float(sp["reverse_m_upper"])
        rev0 = float(expected_loss.reverse_stress_m(self.P0, coh0, 12, target, m_up))
        revb = expected_loss.reverse_stress_m(self.Pb, cohb, 12, target, m_up)
        rlo, rhi, _, _ = _ci(revb, self.level)
        inc_d0 = float(
            expected_loss.scenario_el(self.P0, coh0, 12, 1.0, 0.0, ead, lgd, include_dormant=True)
        )
        # Raw-leak sensitivity: charge-off and paid-off rows estimated from data instead of identity.
        stays = {r["FROM_STATE"]: r["n"] for r in self.dq["absorbing_stays"]}
        leak = self.P0.copy()
        an = pd.DataFrame(self.dq["transition_anomalies"])
        for s in (C.CHARGE_OFF, C.PAID_OFF):
            row = np.zeros(N_STATES)
            row[IDX[s]] = stays.get(s, 0)
            for r in an[s == an.FROM_STATE].itertuples(index=False):
                row[IDX[r.TO_STATE]] += r.n
            if row.sum() > 0:
                leak[IDX[s]] = row / row.sum()
        pi = np.zeros(N_STATES)
        pi[:N_TRANSIENT] = coh0
        co_abs = float(markov.forecast(pi, self.P0, 12)[CO_IDX])
        co_leak = float(markov.forecast(pi, leak, 12)[CO_IDX])
        self.res["stress"] = {
            "ead": ead,
            "lgd": lgd,
            "currency": sp["currency"],
            "cohort_m0": {s: float(coh0[IDX[s]]) for s in C.TRANSIENT},
            "reverse_m": rev0,
            "reverse_m_lo": rlo,
            "reverse_m_hi": rhi,
            "reverse_unreached_share": float(np.mean(np.isnan(revb))),
            "el12_base_incl_dormant": inc_d0,
            "raw_leak": {"co_in_12m_absorbing": co_abs, "co_in_12m_raw_leak": co_leak},
        }
        cur = sp["currency"]
        b12 = tab[(tab.scenario == "BASE") & (tab.horizon == 12)].iloc[0]
        s12 = tab[(tab.scenario == "SEVERE") & (tab.horizon == 12)].iloc[0]
        m12 = tab[(tab.scenario == "MODERATE") & (tab.horizon == 12)].iloc[0]
        self.show("currency", cur, "text")
        self.show("ead", ead, "money0")
        self.show("lgd", lgd, "pct0")
        self.show("el12_base", b12.el, "money0")
        self.show("el12_base_lo", b12.el_lo, "money0")
        self.show("el12_base_hi", b12.el_hi, "money0")
        self.show("el12_mod", m12.el, "money0")
        self.show("el12_sev", s12.el, "money0")
        self.show("el12_sev_lo", s12.el_lo, "money0")
        self.show("el12_sev_hi", s12.el_hi, "money0")
        self.show("el12_sev_uplift", s12.uplift, "pct0")
        self.show("el12_sev_uplift_lo", s12.uplift_lo, "pct0")
        self.show("el12_sev_uplift_hi", s12.uplift_hi, "pct0")
        self.show("el12_mod_uplift", m12.uplift, "pct0")
        self.show("el12_mod_lo", m12.el_lo, "money0")
        self.show("el12_mod_hi", m12.el_hi, "money0")
        self.show(
            "el12_base_cos", b12.expected_chargeoffs, "num1", "expected charge-offs in 12M (base)"
        )
        self.show("rev_m", rev0, "num2", "reverse-stress multiplier")
        self.show("rev_m_lo", rlo, "num2")
        self.show("rev_m_hi", rhi, "num2")
        self.show(
            "cohort_open_m0", float(coh0[1:].sum()), "int", "open cohort (1-29..120-149) at M0"
        )
        self.show("cohort_dormant_m0", float(coh0[0]), "int")
        # Replicates for live intervals in the app (aggregated matrices, no client data).
        B = self.Pb.shape[0]
        reps = []
        for i, f in enumerate(C.MARKOV_ORDER):
            for j, t in enumerate(C.MARKOV_ORDER):
                reps.append(
                    pd.DataFrame(
                        {"rep": np.arange(B), "FROM_STATE": f, "TO_STATE": t, "p": self.Pb[:, i, j]}
                    )
                )
        self.cubes["stress_bootstrap_matrices"] = pd.concat(reps, ignore_index=True)
        self.cubes["stress_bootstrap_cohort"] = pd.DataFrame(
            {
                "rep": np.repeat(np.arange(B), N_TRANSIENT),
                "STATE": np.tile(C.TRANSIENT, B),
                "n": cohb.reshape(-1),
            }
        )
        # Current-mix run-off forecast from month 0.
        self.cubes["forecast_current"] = forecasting.runoff(coh0, self.P0, [3, 6, 12])

    # ------------------------------------------------------------------ export
    def export(self) -> None:
        """Write cubes, backtest results, results.json and generated documents."""
        sup = int(self.p["suppress_cube_n"])
        self.cubes["stock_cube"] = self.q("SELECT * FROM stock_cube")
        self.cubes["transition_cube"] = self.q("SELECT * FROM transition_cube")
        self.cubes["flow_table"] = self.q("SELECT * FROM flow_table")
        self.cubes["entry_exit_flows"] = self.q("SELECT * FROM entry_exit_flows")
        seg_stock = self.q("SELECT * FROM segment_stock_cube")
        seg_stock["suppressed"] = seg_stock.n < sup
        seg_stock.loc[seg_stock.suppressed, "n"] = np.nan
        self.cubes["segment_stock_cube"] = seg_stock
        seg_tr = self.q("SELECT * FROM segment_transition_cube")
        rown = seg_tr.groupby(["SEG_TYPE", "SEGMENT", "PERIOD", "FROM_STATE"], as_index=False)[
            "n"
        ].sum()
        seg_tr["suppressed"] = seg_tr.n < sup
        seg_tr.loc[seg_tr.suppressed, "n"] = np.nan
        self.cubes["segment_transition_cube"] = seg_tr
        rown["suppressed"] = rown.n < sup
        rown.loc[rown.suppressed, "n"] = np.nan
        self.cubes["segment_transition_rows"] = rown
        for name, df in self.cubes.items():
            bad = {"ID", "CLIENT_ID", "client_id", "id"} & set(df.columns)
            if bad:
                raise RuntimeError(f"cube {name} carries identifier columns {bad}")
            write_parquet(df, CUBES_DIR / f"{name}.parquet")
        write_parquet(self.bt, PROCESSED_DIR / "backtest_results.parquet")
        self.bt.to_csv(VALIDATION_DIR / "backtest_results.csv", index=False)
        self.calib.to_csv(VALIDATION_DIR / "chargeoff_calibration.csv", index=False)
        self.cubes["stationarity"].to_csv(VALIDATION_DIR / "stationarity_tests.csv", index=False)
        self.cubes["mob_homogeneity"].to_csv(
            VALIDATION_DIR / "mob_homogeneity_tests.csv", index=False
        )
        self.cubes["history_test"].to_csv(VALIDATION_DIR / "history_test.csv", index=False)
        self.cubes["mob_band_probabilities"].to_csv(
            VALIDATION_DIR / "mob_band_probabilities.csv", index=False
        )
        write_parquet(self.calib, CUBES_DIR / "chargeoff_calibration.parquet")

        m = self.m
        self.show("credit_rows", m["credit_rows"], "int", "monthly status records")
        self.show("credit_clients", m["credit_clients"], "int", "credit clients")
        self.show("app_rows", m["app_rows"], "int")
        self.show("matched_clients", m["matched_clients"], "int")
        self.show("credit_only", m["credit_only"], "int")
        self.show(
            "opened_clients", len(self.clients), "int", "accounts with at least one open month"
        )
        self.show("x_only_clients", m["x_only_clients"], "int")
        self.show("c_to_c", m["c_to_c"], "int")
        self.show("c_total", m["c_transitions_total"], "int")
        self.show("c_to_open", m["c_to_open"], "int")
        self.show("dormant_return", self.dq["dormant_return_share"], "pct0")
        self.show("co_anomaly_n", m["co_to_nonco_consecutive_nonx"], "int")
        self.show("co_anomaly_den", m["co_transitions_nonx"], "int")
        self.show(
            "co_anomaly_share", m["co_to_nonco_consecutive_nonx"] / m["co_transitions_nonx"], "pct1"
        )
        self.show("lead_x_share", m["first_status_x_clients"] / m["credit_clients"], "pct1")
        self.show("trunc_fired", "fired" if self.trunc["fired"] else "did not fire", "text")
        self.show("app_above_cut", self.trunc["app_ids_above_cut"], "int")
        self.show("dq_pass", self.dq["status_summary"].get("PASS", 0), "int")
        self.show("dq_warn", self.dq["status_summary"].get("WARNING", 0), "int")
        self.show("dq_fail", self.dq["status_summary"].get("FAIL", 0), "int")
        self.show("ci_level", self.level, "pct0")
        self.show("anomaly_co12_abs", self.res["stress"]["raw_leak"]["co_in_12m_absorbing"], "num1")
        self.show("anomaly_co12_leak", self.res["stress"]["raw_leak"]["co_in_12m_raw_leak"], "num1")
        self.show("el12_base_incl_dormant", self.res["stress"]["el12_base_incl_dormant"], "money0")
        self.show("app_dup_ids", m["app_duplicated_ids"], "int")
        self.show("dq_checks", len(self.dq["checks"]), "int")
        self.show("pilot_agree", sum(r["agrees"] for r in self.dq["pilot_reconciliation"]), "int")
        self.show("pilot_items", len(self.dq["pilot_reconciliation"]), "int")
        self.show("bt_missing_share", self.res["backtest"]["missing_share_mean"], "pct1")
        self.show("redelinq_n", self.res["cure_redelinquency"]["cured_with_window"], "int")
        st = self.res["stationarity"]["oot_mae_pp_origin_m12_h12"]
        self.show("oot_first_half", st["first_half"], "num2")
        self.show("oot_expanding", st["expanding_to_m12"], "num2")
        self.res["timings"] = {k: round(v, 2) for k, v in self.timings.items()}
        self.res["params"] = {
            "min_n_row": self.p["min_n_row"],
            "warn_n_row": self.p["warn_n_row"],
            "suppress_cube_n": sup,
            "mob_bands": self.p["mob_bands"],
            "seed": self.p["seed"],
        }
        write_json(RESULTS_PATH, self.res)
        reporting.write_result_docs(self.res, self.dq, self.cubes, self.p)
        reporting.write_figures(self.cubes, self.bt, self.res, self.p)
        log.info("wrote %d cubes, results.json and generated docs", len(self.cubes))


def run(stage: str = "all") -> None:
    """Run the build up to ``stage`` ('audit' or 'all')."""
    t0 = time.perf_counter()
    params = load_params()
    ensure_dirs()
    b = Build(params)
    with timed("SQL layer"):
        b.sql()
    with timed("audit"):
        b.audit()
    if stage == "audit":
        return
    with timed("load frames"):
        b.load_frames()
    with timed("bootstrap"):
        b.run_bootstrap()
    with timed("roll rates"):
        b.roll_rates()
    with timed("prevalence"):
        b.prevalence()
    with timed("vintage"):
        b.vintages()
    with timed("cure"):
        b.cure()
    with timed("segments"):
        b.segments()
    with timed("absorbing chain"):
        b.absorbing_chain()
    with timed("backtest"):
        b.backtest()
    with timed("stress"):
        b.stress()
    b.timings["total_before_export"] = time.perf_counter() - t0
    with timed("export"):
        b.export()
    log.info("build finished in %.1fs", time.perf_counter() - t0)


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stage", choices=["audit", "all"], default="all")
    run(ap.parse_args().stage)


if __name__ == "__main__":
    main()
