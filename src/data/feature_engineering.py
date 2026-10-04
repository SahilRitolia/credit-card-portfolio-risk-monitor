"""Independent pandas implementation of the panel logic, and per-client sufficient
statistics for the bootstrap.

The pandas functions (``reference_*``) re-derive the SQL outputs from raw rows. They exist
only so tests can reconcile SQL against an independent implementation; the pipeline never
uses them to replace SQL results.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.bootstrap import StatRegistry
from src.models.markov import IDX, N_STATES, N_TRANSIENT
from src.utils import constants as C

OPEN_RAW = {"0", "1", "2", "3", "4", "5"}
D30_RAW = {"1", "2", "3", "4", "5"}


# ---------------------------------------------------------------------------
# Reference (pandas) implementation for reconciliation tests
# ---------------------------------------------------------------------------
def map_states(raw: pd.Series, mapping: str = "evidence_based") -> pd.Series:
    """Map raw STATUS to canonical states under either mapping; invalid values become NaN."""
    table = C.EVIDENCE_MAPPING if mapping == "evidence_based" else C.LITERAL_MAPPING
    if mapping not in {"evidence_based", "source_literal"}:
        raise ValueError(f"unknown STATE_MAPPING {mapping!r}")
    return raw.astype(str).str.strip().str.upper().map(table)


def reference_gap_flags(credit: pd.DataFrame) -> pd.DataFrame:
    """Successive-record pairs per ID with month difference and gap flag."""
    d = credit.sort_values(["ID", "MONTHS_BALANCE"]).copy()
    d["previous_month"] = d.groupby("ID")["MONTHS_BALANCE"].shift(1)
    d = d.dropna(subset=["previous_month"])
    d["month_difference"] = d.MONTHS_BALANCE - d.previous_month
    d["gap_flag"] = np.select(
        [d.month_difference == 1, d.month_difference == 2, d.month_difference == 0],
        ["consecutive", "single_gap", "duplicate_month"],
        "multi_gap",
    )
    return d.rename(columns={"MONTHS_BALANCE": "current_month"})[
        ["ID", "previous_month", "current_month", "month_difference", "gap_flag"]
    ].reset_index(drop=True)


def reference_panel(
    credit: pd.DataFrame, mob_bands: list[dict], excluded: set[int] | None = None
) -> pd.DataFrame:
    """Panel with OPEN_MONTH, MOB, RECORD_MOB, STATE and flags."""
    d = credit.copy()
    d["STATUS"] = d.STATUS.astype(str).str.strip().str.upper()
    if excluded:
        d = d[~d.ID.isin(excluded)]
    d["STATE"] = map_states(d.STATUS)
    d = d.dropna(subset=["STATE"])
    first = d.groupby("ID").MONTHS_BALANCE.min().rename("FIRST_MONTH")
    opn = d[d.STATUS != "X"].groupby("ID").MONTHS_BALANCE.min().rename("OPEN_MONTH")
    d = d.join(first, on="ID").join(opn, on="ID")
    d["MOB"] = np.where(d.MONTHS_BALANCE >= d.OPEN_MONTH, d.MONTHS_BALANCE - d.OPEN_MONTH, np.nan)
    d["RECORD_MOB"] = d.MONTHS_BALANCE - d.FIRST_MONTH
    d["IS_OPENED"] = d.MOB.notna()
    d["IS_30P"] = d.STATUS.isin(D30_RAW)
    d["IS_60P"] = d.STATUS.isin({"2", "3", "4", "5"})
    d["IS_90P"] = d.STATUS.isin({"3", "4", "5"})
    d["IS_CHARGEOFF"] = d.STATUS == "5"
    band = pd.Series("pre-open", index=d.index)
    for b in mob_bands:
        band = band.mask((b["lo"] <= d.MOB) & (b["hi"] >= d.MOB), b["label"])
    d["MOB_BAND"] = band
    return d.sort_values(["ID", "MONTHS_BALANCE"]).reset_index(drop=True)


def reference_transitions(panel: pd.DataFrame) -> pd.DataFrame:
    """Consecutive-month transitions from opened, transient origins."""
    d = panel.sort_values(["ID", "MONTHS_BALANCE"])
    nxt = d.groupby("ID")[["MONTHS_BALANCE", "STATE"]].shift(-1)
    t = d.assign(DEST_MONTH=nxt.MONTHS_BALANCE, TO_STATE=nxt.STATE)
    t = t[t.IS_OPENED & (t.DEST_MONTH == t.MONTHS_BALANCE + 1)]
    t = t[~t.STATE.isin(C.ABSORBING)]
    return t.rename(columns={"MONTHS_BALANCE": "ORIGIN_MONTH", "STATE": "FROM_STATE"})[
        ["ID", "ORIGIN_MONTH", "DEST_MONTH", "FROM_STATE", "TO_STATE", "MOB", "MOB_BAND"]
    ].reset_index(drop=True)


def reference_vintage_curves(panel: pd.DataFrame) -> pd.DataFrame:
    """Monthly vintage x MOB ever-metrics under the observability rule."""
    op = panel[panel.IS_OPENED]
    cl = op.groupby("ID").agg(OPEN_MONTH=("OPEN_MONTH", "first"))
    for flag, name in (
        ("IS_30P", "F30"),
        ("IS_60P", "F60"),
        ("IS_90P", "F90"),
        ("IS_CHARGEOFF", "FCO"),
    ):
        cl[name] = op[op[flag]].groupby("ID").MOB.min()
    rows = []
    for v, g in cl.groupby("OPEN_MONTH"):
        for k in range(0, int(-v) + 1):
            rows.append(
                {
                    "VINTAGE_MONTH": int(v),
                    "MOB": k,
                    "n_accounts": len(g),
                    "ever_30p": int((k >= g.F30).sum()),
                    "ever_60p": int((k >= g.F60).sum()),
                    "ever_90p": int((k >= g.F90).sum()),
                    "ever_co": int((k >= g.FCO).sum()),
                }
            )
    return pd.DataFrame(rows)


def reference_cure_episodes(panel: pd.DataFrame, max_h: int) -> pd.DataFrame:
    """30+ episodes with event type and month, looked up by calendar month."""
    idx = panel.set_index(["ID", "MONTHS_BALANCE"])
    state_at = idx.STATE.to_dict()
    opened_at = idx.IS_OPENED.to_dict()
    out = []
    for r in panel[panel.IS_OPENED & panel.IS_30P].itertuples(index=False):
        prev_key = (r.ID, r.MONTHS_BALANCE - 1)
        prev_ok = prev_key in state_at and bool(opened_at[prev_key])
        prev_state = state_at[prev_key] if prev_ok else None
        if prev_ok and prev_state in C.DPD30_STATES:
            continue
        if r.STATE == C.CHARGE_OFF:
            etype, ej = "CHARGED-OFF", 0
        else:
            etype, ej = "STILL 30+", None
            for j in range(1, max_h + 1):
                s = state_at.get((r.ID, r.MONTHS_BALANCE + j))
                if s in (C.B0, C.PAID_OFF):
                    etype, ej = "CURED", j
                    break
                if s == C.CHARGE_OFF:
                    etype, ej = "CHARGED-OFF", j
                    break
                if s is None or s == C.DORMANT:
                    etype, ej = "CENSORED", j
                    break
        out.append(
            {
                "ID": r.ID,
                "ENTRY_MONTH": r.MONTHS_BALANCE,
                "ENTRY_STATE": r.STATE,
                "PREV_STATE": prev_state or "none",
                "LEFT_CENSORED": not prev_ok,
                "EVENT_TYPE": etype,
                "EVENT_J": ej,
            }
        )
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Per-client sufficient statistics for the bootstrap
# ---------------------------------------------------------------------------
CURE_GROUPS = ["All episodes", "Entry 30-59", "Entry 60+", "From 1-29", "From dormant"]
PREV_STATES = [C.B0, C.DPD30_STATES, C.DPD60_STATES, C.DPD90_STATES, C.CHARGE_OFF, C.PAID_OFF]
PREV_NAMES = ["open", "30p", "60p", "90p", "co", "paid_off"]


def _sidx(states: pd.Series) -> np.ndarray:
    return states.map(IDX).to_numpy(dtype=np.int64)


def build_client_stats(
    clients: np.ndarray,
    panel: pd.DataFrame,
    trans: pd.DataFrame,
    episodes: pd.DataFrame,
    vint: pd.DataFrame,
    seg: pd.DataFrame,
    params: dict,
    pairs: list[tuple[int, int]],
    origins: list[int],
) -> StatRegistry:
    """Assemble the client statistic matrix blocks used by every bootstrap metric.

    ``panel`` holds opened rows (ID, MONTHS_BALANCE, STATE, RAW_STATUS);
    ``trans`` holds transitions (ID, DEST_MONTH, FROM_STATE, TO_STATE, MOB_BAND, AGE_BAND,
    INCOME_BAND); ``episodes`` is ``cure_episode_groups``; ``vint`` is ``vintage_clients``;
    ``seg`` is ``segment`` membership (ID, SEG_INDEX, eligible/ever60 flags).
    """
    pos = pd.Series(np.arange(len(clients)), index=clients)
    reg = StatRegistry(n_clients=len(clients))
    NS = N_STATES

    # A. transitions by destination month (60 x 6 x 8)
    ci = pos.loc[trans.ID].to_numpy()
    f, t = _sidx(trans.FROM_STATE), _sidx(trans.TO_STATE)
    dm = trans.DEST_MONTH.to_numpy() + 59
    reg.add("trans_dm", (60, N_TRANSIENT, NS), ci, (dm * N_TRANSIENT + f) * NS + t)

    # B. by MOB band (full window)
    labels = [b["label"] for b in params["mob_bands"]]
    bi = trans.MOB_BAND.map({lab: i for i, lab in enumerate(labels)}).to_numpy()
    reg.add("trans_band", (len(labels), N_TRANSIENT, NS), ci, (bi * N_TRANSIENT + f) * NS + t)

    # C. by segment (age bands then income bands; full window)
    seg_labels = seg_label_list(params)
    smap = {lab: i for i, lab in enumerate(seg_labels)}
    parts_c, parts_f = [], []
    for col, prefix in (("AGE_BAND", "age_band:"), ("INCOME_BAND", "income_band:")):
        m = trans[col].notna().to_numpy()
        si = trans.loc[m, col].map(lambda v, p=prefix: smap[p + v]).to_numpy()
        parts_c.append(ci[m])
        parts_f.append((si * N_TRANSIENT + f[m]) * NS + t[m])
    reg.add(
        "trans_seg",
        (len(seg_labels), N_TRANSIENT, NS),
        np.concatenate(parts_c),
        np.concatenate(parts_f),
    )

    # D. prevalence by month (61 x 6 indicators)
    pci = pos.loc[panel.ID].to_numpy()
    mi = panel.MONTHS_BALANCE.to_numpy() + 60
    st = panel.STATE.to_numpy()
    pc, pf = [], []
    for k, sel in enumerate(
        [
            np.isin(st, C.OPEN_STATES),
            np.isin(st, C.DPD30_STATES),
            np.isin(st, C.DPD60_STATES),
            np.isin(st, C.DPD90_STATES),
            st == C.CHARGE_OFF,
            st == C.PAID_OFF,
        ]
    ):
        pc.append(pci[sel])
        pf.append(mi[sel] * len(PREV_NAMES) + k)
    reg.add("prevalence", (61, len(PREV_NAMES)), np.concatenate(pc), np.concatenate(pf))

    # E/F. backtest cohorts and portfolio mixes
    state_lookup = panel.set_index(["ID", "MONTHS_BALANCE"]).STATE
    for t0, h in pairs:
        at0 = panel[(t0 == panel.MONTHS_BALANCE) & panel.STATE.isin(C.TRANSIENT)]
        end = state_lookup.reindex(list(zip(at0.ID, at0.MONTHS_BALANCE + h, strict=True)))
        end_idx = end.map(IDX).fillna(NS).to_numpy(dtype=np.int64)
        reg.add(
            f"cohort_{t0}_{h}",
            (N_TRANSIENT, NS + 1),
            pos.loc[at0.ID].to_numpy(),
            _sidx(at0.STATE) * (NS + 1) + end_idx,
        )
    for t0 in origins:
        a = panel[t0 == panel.MONTHS_BALANCE]
        reg.add(f"portfolio_{t0}", (NS,), pos.loc[a.ID].to_numpy(), _sidx(a.STATE))

    # G. current cohort at month 0 (transient states)
    m0 = panel[(panel.MONTHS_BALANCE == 0) & panel.STATE.isin(C.TRANSIENT)]
    reg.add("cohort_m0", (N_TRANSIENT,), pos.loc[m0.ID].to_numpy(), _sidx(m0.STATE))

    # H. vintage checkpoints (21 quarters x K checkpoints x 5)
    ks = params["vintage"]["checkpoints"]
    vc, vf = [], []
    vci = pos.loc[vint.ID].to_numpy()
    q = vint.VINTAGE_QTR.to_numpy()
    om = vint.OPEN_MONTH.to_numpy()
    firsts = [None, vint.FIRST_30P_MOB, vint.FIRST_60P_MOB, vint.FIRST_90P_MOB, vint.FIRST_CO_MOB]
    for ki, k in enumerate(ks):
        obs = om + k <= 0
        for j, fm in enumerate(firsts):
            sel = obs if fm is None else obs & (fm.fillna(10**6).to_numpy() <= k)
            vc.append(vci[sel])
            vf.append((q[sel] * len(ks) + ki) * 5 + j)
    reg.add("vintage", (21, len(ks), 5), np.concatenate(vc), np.concatenate(vf))

    # I. cure: hazards (G x J x 4), immediate (G x 2), fixed window (G x K x 3), raw (G x K x 5)
    H = max(params["cure"]["horizons"])
    hz = params["cure"]["horizons"]
    eci = pos.loc[episodes.ID].to_numpy()
    g = episodes.GRP.map({n: i for i, n in enumerate(CURE_GROUPS)}).to_numpy()
    ej = episodes.EVENT_J.fillna(99).to_numpy()
    et = episodes.EVENT_TYPE.to_numpy()
    em = episodes.ENTRY_MONTH.to_numpy()
    hc, hf = [], []
    for j in range(1, H + 1):
        for col, sel in enumerate(
            [
                ej >= j,
                (ej == j) & (et == "CURED"),
                (ej == j) & (et == "CHARGED-OFF"),
                (ej == j) & (et == "CENSORED"),
            ]
        ):
            sel = sel & (ej >= 1)
            hc.append(eci[sel])
            hf.append((g[sel] * H + (j - 1)) * 4 + col)
    reg.add("cure_hazard", (len(CURE_GROUPS), H, 4), np.concatenate(hc), np.concatenate(hf))
    ic = [eci[ej == 0], eci]
    iff = [g[ej == 0] * 2 + 0, g * 2 + 1]
    reg.add("cure_immediate", (len(CURE_GROUPS), 2), np.concatenate(ic), np.concatenate(iff))
    fc, ff, rc, rf = [], [], [], []
    for ki, k in enumerate(hz):
        within = ej <= k
        complete = em + k <= 0
        elig = complete & ~((et == "CENSORED") & within)
        for col, sel in enumerate(
            [elig, elig & within & (et == "CURED"), elig & within & (et == "CHARGED-OFF")]
        ):
            fc.append(eci[sel])
            ff.append((g[sel] * len(hz) + ki) * 3 + col)
        for col, sel in enumerate(
            [
                np.ones_like(within),
                within & (et == "CURED"),
                within & (et == "CHARGED-OFF"),
                within & (et == "CENSORED"),
                ~within,
            ]
        ):
            rc.append(eci[sel])
            rf.append((g[sel] * len(hz) + ki) * 5 + col)
    reg.add("cure_fixed", (len(CURE_GROUPS), len(hz), 3), np.concatenate(fc), np.concatenate(ff))
    reg.add("cure_raw", (len(CURE_GROUPS), len(hz), 5), np.concatenate(rc), np.concatenate(rf))

    # J. segments (9 x 6): eligible_h, ever60_h, open_months, months_30p, trans_30p, cures
    sc, sf, sv = [], [], []
    for col, name in enumerate(
        ["eligible_h", "ever60_h", "open_months", "months_30p", "trans_30p", "cures"]
    ):
        sub = seg[seg[name] > 0]
        sc.append(pos.loc[sub.ID].to_numpy())
        sf.append(sub.SEG_INDEX.to_numpy() * 6 + col)
        sv.append(sub[name].to_numpy(dtype=float))
    reg.add(
        "segment", (len(seg_labels), 6), np.concatenate(sc), np.concatenate(sf), np.concatenate(sv)
    )
    return reg


def seg_label_list(params: dict) -> list[str]:
    """Segment keys in bootstrap order: 'age_band:<label>' then 'income_band:<label>'."""
    ages = [b["label"] for b in params["age_bands"]]
    incomes = ["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"]
    return [f"age_band:{a}" for a in ages] + [f"income_band:{i}" for i in incomes]
