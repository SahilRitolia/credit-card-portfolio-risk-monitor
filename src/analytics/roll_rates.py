"""Roll-rate matrices, named roll metrics, suppression and the source-literal sensitivity.

Inputs are transient-origin count arrays (..., 6, 8) in MARKOV_ORDER, produced from the SQL
tables (``roll_counts``, ``transition_cube``) or from bootstrap replicate sums.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.markov import IDX, N_TRANSIENT, estimate
from src.utils import constants as C

ROLL_ORIGINS: list[str] = [C.DORMANT, C.B0, C.B1, C.B2, C.B3, C.B4]
DELINQ_ORIGINS: list[str] = [C.B1, C.B2, C.B3, C.B4]


def _ratio(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def named_metrics(counts: np.ndarray) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Named roll metrics on view A as (numerator, denominator) arrays over the batch.

    Mirrors ``named_rolls`` in sql/06_roll_rates.sql (reconciled in tests).
    """
    c = np.asarray(counts, dtype=float)
    i = IDX
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    dl = [i[s] for s in DELINQ_ORIGINS]
    den = c[..., dl, :].sum(axis=(-1, -2))
    out["cure_30p"] = (c[..., dl, :][..., [i[C.B0], i[C.PAID_OFF]]].sum(axis=(-1, -2)), den)
    out["cure_30p_to_1_29"] = (c[..., dl, i[C.B0]].sum(axis=-1), den)
    out["cure_30p_to_paid_off"] = (c[..., dl, i[C.PAID_OFF]].sum(axis=-1), den)
    rank = {C.B0: 1, C.B1: 2, C.B2: 3, C.B3: 4, C.B4: 5, C.CHARGE_OFF: 6}
    for b in [C.B0, C.B1, C.B2, C.B3, C.B4]:
        row = c[..., i[b], :]
        out[f"persistence_{b}"] = (row[..., i[b]], row.sum(axis=-1))
        worse = [i[s] for s, r in rank.items() if r > rank[b]]
        out[f"forward_{b}"] = (row[..., worse].sum(axis=-1), row.sum(axis=-1))
    r1 = c[..., i[C.B1], :]
    out["roll_30_59_to_60p"] = (
        r1[..., [i[C.B2], i[C.B3], i[C.B4], i[C.CHARGE_OFF]]].sum(axis=-1),
        r1.sum(axis=-1),
    )
    r2 = c[..., i[C.B2], :]
    out["severe_roll_60_89_to_90p"] = (
        r2[..., [i[C.B3], i[C.B4], i[C.CHARGE_OFF]]].sum(axis=-1),
        r2.sum(axis=-1),
    )
    r9 = c[..., [i[C.B3], i[C.B4]], :]
    out["roll_90p_to_co"] = (r9[..., i[C.CHARGE_OFF]].sum(axis=-1), r9.sum(axis=(-1, -2)))
    return out


def named_rates(counts: np.ndarray) -> dict[str, np.ndarray]:
    """Named metrics as rates."""
    return {k: _ratio(n, d) for k, (n, d) in named_metrics(counts).items()}


def matrix_table(
    point_counts: np.ndarray,
    boot_counts: np.ndarray | None,
    view: str = "A",
    min_n: int = 30,
    warn_n: int = 100,
    level: float = 0.95,
) -> pd.DataFrame:
    """Long table of a roll-rate matrix with n, probability and bootstrap interval.

    Rows with fewer than ``min_n`` transitions are marked suppressed (probability NaN);
    rows below ``warn_n`` carry a warning flag. View B drops DORMANT destinations.
    """
    drop = view == "B"
    P = estimate(point_counts, drop_dormant_dest=drop)
    pc = np.asarray(point_counts, dtype=float).copy()
    if drop:
        pc[:, IDX[C.DORMANT]] = 0.0
    row_n = pc.sum(axis=1)
    lo = hi = se = degen = None
    if boot_counts is not None:
        Pb = estimate(boot_counts, drop_dormant_dest=drop)
        a = (1 - level) / 2
        lo = np.quantile(Pb, a, axis=0)
        hi = np.quantile(Pb, 1 - a, axis=0)
        se = Pb.std(axis=0, ddof=1)
        degen = (Pb == 0).mean(axis=0) >= 0.5
    rows = []
    for fi, f in enumerate(C.MARKOV_ORDER[:N_TRANSIENT]):
        sup = row_n[fi] < min_n
        for ti, t in enumerate(C.MARKOV_ORDER):
            if drop and t == C.DORMANT:
                continue
            if drop and f == C.DORMANT:
                continue
            rows.append(
                {
                    "FROM_STATE": f,
                    "TO_STATE": t,
                    "n": float(pc[fi, ti]),
                    "row_n": float(row_n[fi]),
                    "p": np.nan if sup else float(P[fi, ti]),
                    "lo": np.nan if (sup or lo is None) else float(lo[fi, ti]),
                    "hi": np.nan if (sup or hi is None) else float(hi[fi, ti]),
                    "se": np.nan if (sup or se is None) else float(se[fi, ti]),
                    "degenerate": bool(degen[fi, ti]) if degen is not None else False,
                    "suppressed": bool(sup),
                    "warn_small_n": bool((not sup) and row_n[fi] < warn_n),
                }
            )
    return pd.DataFrame(rows)


def counts_from_long(df: pd.DataFrame) -> np.ndarray:
    """(6, 8) counts from a long FROM_STATE/TO_STATE/n frame (missing cells are 0)."""
    out = np.zeros((N_TRANSIENT, len(C.MARKOV_ORDER)))
    if df.empty:
        return out
    g = df.groupby(["FROM_STATE", "TO_STATE"], as_index=False)["n"].sum()
    for f, t, n in g.itertuples(index=False):
        if f in IDX and IDX[f] < N_TRANSIENT and t in IDX:
            out[IDX[f], IDX[t]] = n
    return out


LITERAL_ORDER: list[str] = ["CURRENT", C.B0, C.B1, C.B2, C.B3, C.B4, C.CHARGE_OFF]


def literal_sensitivity(raw_counts: pd.DataFrame) -> dict[str, object]:
    """Matrix under the source-literal reading (C = CURRENT, X outside the book).

    ``raw_counts`` has FROM_STATUS, TO_STATUS, n on raw statuses. Transitions touching X are
    dropped (X is 'outside'); CHARGE-OFF is absorbing. The CURRENT row demonstrates the
    degeneracy: it essentially never deteriorates.
    """
    lit = {
        "C": "CURRENT",
        "0": C.B0,
        "1": C.B1,
        "2": C.B2,
        "3": C.B3,
        "4": C.B4,
        "5": C.CHARGE_OFF,
    }
    df = raw_counts[raw_counts.FROM_STATUS.isin(lit) & raw_counts.TO_STATUS.isin(lit)].copy()
    df["F"] = df.FROM_STATUS.map(lit)
    df["T"] = df.TO_STATUS.map(lit)
    idx = {s: k for k, s in enumerate(LITERAL_ORDER)}
    cnt = np.zeros((len(LITERAL_ORDER), len(LITERAL_ORDER)))
    for f, t, n in df[["F", "T", "n"]].itertuples(index=False):
        cnt[idx[f], idx[t]] += n
    rs = cnt.sum(axis=1, keepdims=True)
    P = np.where(rs > 0, cnt / np.where(rs > 0, rs, 1.0), 0.0)
    cur = idx["CURRENT"]
    worse = [idx[s] for s in LITERAL_ORDER[1:]]
    table = pd.DataFrame(P, index=LITERAL_ORDER, columns=LITERAL_ORDER)
    return {
        "matrix": table,
        "counts": pd.DataFrame(cnt, index=LITERAL_ORDER, columns=LITERAL_ORDER),
        "current_row_n": float(rs[cur, 0]),
        "current_persistence": float(P[cur, cur]),
        "current_deterioration": float(P[cur, worse].sum()),
    }
