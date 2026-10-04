"""Vintage observability and cure episodes: known answers and SQL-vs-pandas reconciliation."""

import numpy as np
import pandas as pd

from src.analytics import cure_rates, vintage
from src.data import feature_engineering as fe


def test_vintage_cells_respect_observability(fixture_db, synthetic_db) -> None:
    for con in (fixture_db, synthetic_db[0]):
        vc = con.execute("SELECT * FROM vintage_curves").df()
        assert (vc.VINTAGE_MONTH + vc.MOB <= 0).all()
        assert (
            vc.groupby("VINTAGE_MONTH")
            .MOB.max()
            .eq(-vc.groupby("VINTAGE_MONTH").VINTAGE_MONTH.first())
            .all()
        )


def test_vintage_denominator_includes_early_closing_accounts(fixture_db) -> None:
    vc = fixture_db.execute("SELECT * FROM vintage_curves WHERE VINTAGE_MONTH = -10").df()
    # client 1003 opens at -10 and its records end at -5; it stays in the denominator at every MOB
    assert (vc.n_accounts == 1).all() and vc.MOB.max() == 10
    assert vc[vc.MOB == 10].records_ended.iloc[0] == 1


def test_vintage_ever_metrics_reconcile(synthetic_db, params) -> None:
    con, credit = synthetic_db
    ref = fe.reference_vintage_curves(fe.reference_panel(credit, params["mob_bands"]))
    sql = con.execute(
        "SELECT VINTAGE_MONTH, MOB, n_accounts, ever_30p, ever_60p, ever_90p, ever_co FROM vintage_curves"
    ).df()
    m = ref.merge(sql, on=["VINTAGE_MONTH", "MOB"], suffixes=("_r", "_s"))
    assert len(m) == len(ref) == len(sql)
    for c in ("n_accounts", "ever_30p", "ever_60p", "ever_90p", "ever_co"):
        assert (m[f"{c}_r"] == m[f"{c}_s"]).all(), c


def test_quarterly_curves_only_where_all_months_observable() -> None:
    rows = [
        {
            "VINTAGE_MONTH": v,
            "VINTAGE_QTR": (v + 60) // 3,
            "MOB": k,
            "n_accounts": 10,
            "ever_30p": 1,
            "ever_60p": 0,
            "ever_90p": 0,
            "ever_co": 0,
        }
        for v in (-3, -2, -1, 0)
        for k in range(0, -v + 1)
    ]
    q = vintage.quarterly_curves(pd.DataFrame(rows))
    # quarter 19 = months -3..-1: a quarterly point exists only up to MOB 1 (limited by month -1)
    assert q[q.VINTAGE_QTR == 19].MOB.max() == 1
    assert q[q.VINTAGE_QTR == 20].MOB.max() == 0
    assert np.allclose(q.ever_30p_rate, 0.1)


def test_cure_episode_known_answers(fixture_db) -> None:
    e = (
        fixture_db.execute("SELECT * FROM cure_episodes ORDER BY ID, ENTRY_MONTH")
        .df()
        .set_index(["ID", "ENTRY_MONTH"])
    )
    assert e.loc[(1001, -5)].EVENT_TYPE == "CURED" and e.loc[(1001, -5)].EVENT_J == 3
    assert (
        e.loc[(1002, -2)].EVENT_TYPE == "CENSORED" and e.loc[(1002, -2)].EVENT_J == 1
    )  # month -1 missing
    assert e.loc[(1004, -6)].EVENT_TYPE == "CHARGED-OFF" and e.loc[(1004, -6)].EVENT_J == 4
    assert e.loc[(1006, -4)].EVENT_TYPE == "CENSORED"  # an X month intervenes
    assert bool(e.loc[(1007, -3)].LEFT_CENSORED)  # first open month is already 30+
    assert e.loc[(1009, -2)].EVENT_TYPE == "CHARGED-OFF" and e.loc[(1009, -2)].EVENT_J == 0


def test_cure_episodes_reconcile(synthetic_db, params) -> None:
    con, credit = synthetic_db
    ref = fe.reference_cure_episodes(fe.reference_panel(credit, params["mob_bands"]), 6)
    sql = con.execute(
        "SELECT ID, ENTRY_MONTH, EVENT_TYPE, EVENT_J, LEFT_CENSORED FROM cure_episodes"
    ).df()
    m = ref.merge(sql, on=["ID", "ENTRY_MONTH"], suffixes=("_r", "_s"))
    assert len(m) == len(ref) == len(sql)
    assert (m.EVENT_TYPE_r == m.EVENT_TYPE_s).all()
    assert (m.LEFT_CENSORED_r == m.LEFT_CENSORED_s).all()
    assert np.allclose(m.EVENT_J_r.astype(float).fillna(-1), m.EVENT_J_s.astype(float).fillna(-1))


def test_cumulative_incidence_sums_to_one_with_censoring(synthetic_db) -> None:
    con, _ = synthetic_db
    hz = con.execute("SELECT * FROM cure_hazards ORDER BY GRP, J").df()
    im = con.execute("SELECT * FROM cure_immediate").df().set_index("GRP")
    for g, d in hz.groupby("GRP"):
        h = d[["at_risk", "cured", "charged_off", "censored"]].to_numpy(float)
        out = cure_rates.cumulative_incidence(
            h, im.loc[g, ["co_at_entry", "episodes"]].to_numpy(float)
        )
        total = out["cif_cure"] + out["cif_co"] + out["still_30p"]
        assert np.allclose(total, 1.0)
        assert np.all(np.diff(out["cif_cure"]) >= -1e-12)


def test_cumulative_incidence_hand_example() -> None:
    # 10 at risk: month 1 cures 4, CO 1, censors 1; month 2 has 4 at risk, cures 2.
    h = np.array([[10, 4, 1, 1], [4, 2, 0, 0]], dtype=float)
    out = cure_rates.cumulative_incidence(h, np.array([0.0, 10.0]))
    assert np.isclose(out["cif_cure"][0], 0.4)
    assert np.isclose(out["cif_cure"][1], 0.4 + 0.5 * 0.5)
    assert np.isclose(out["cif_co"][1], 0.1)
    assert np.isclose(out["still_30p"][1], 0.25)
