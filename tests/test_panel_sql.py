"""Panel, gaps and transitions: known answers on the hand-built fixture and SQL-vs-pandas
reconciliation on a random synthetic panel."""

import numpy as np
import pandas as pd

from src.analytics.roll_rates import counts_from_long
from src.data import feature_engineering as fe


def _panel(con) -> pd.DataFrame:
    return con.execute("SELECT * FROM panel ORDER BY ID, MONTHS_BALANCE").df()


def test_open_month_mob_and_record_mob_with_leading_x(fixture_db) -> None:
    p = _panel(fixture_db)
    c = p[p.ID == 1001].set_index("MONTHS_BALANCE")
    assert (c.OPEN_MONTH == -7).all()
    assert pd.isna(c.loc[-9, "MOB"]) and pd.isna(c.loc[-8, "MOB"])
    assert not c.loc[-9, "IS_OPENED"]
    assert c.loc[-7, "MOB"] == 0 and c.loc[-7, "RECORD_MOB"] == 2
    assert c.loc[0, "MOB"] == 7 and c.loc[-9, "MOB_BAND"] == "pre-open"


def test_x_only_client_is_never_opened(fixture_db) -> None:
    p = _panel(fixture_db)
    assert not p[p.ID == 1005].IS_OPENED.any()
    oc = fixture_db.execute("SELECT ID FROM opened_clients").df()
    assert 1005 not in set(oc.ID)


def test_gap_detection_single_and_multi(fixture_db, credit_fixture) -> None:
    g = fixture_db.execute(
        "SELECT * FROM dq_month_gaps WHERE gap_flag <> 'consecutive' ORDER BY ID, current_month"
    ).df()
    flags = list(zip(g.ID, g.gap_flag, strict=True))
    assert flags == [(1002, "single_gap"), (1002, "single_gap"), (1003, "multi_gap")]
    ref = fe.reference_gap_flags(credit_fixture)
    sql_all = fixture_db.execute("SELECT * FROM dq_month_gaps").df()
    assert len(ref) == len(sql_all)
    assert (
        ref.gap_flag.value_counts().sort_index() == sql_all.gap_flag.value_counts().sort_index()
    ).all()


def test_non_consecutive_rows_never_become_transitions(fixture_db) -> None:
    t = fixture_db.execute(
        "SELECT * FROM transitions_all WHERE ID = 1002 ORDER BY ORIGIN_MONTH"
    ).df()
    assert list(zip(t.ORIGIN_MONTH, t.DEST_MONTH, strict=True)) == [(-6, -5), (-3, -2)]
    t3 = fixture_db.execute("SELECT * FROM transitions_all WHERE ID = 1003").df()
    assert list(t3.ORIGIN_MONTH) == [-6]
    assert (
        (
            fixture_db.execute(
                "SELECT MAX(DEST_MONTH - ORIGIN_MONTH) FROM transitions_all"
            ).fetchone()[0]
        )
        == 1
    )


def test_absorbing_departures_go_to_anomaly_table(fixture_db) -> None:
    an = fixture_db.execute("SELECT * FROM transition_anomalies").df()
    assert list(zip(an.ID, an.FROM_STATE, an.TO_STATE, strict=True)) == [
        (1004, "CHARGE-OFF", "PAID-OFF")
    ]
    t = fixture_db.execute("SELECT * FROM transitions").df()
    assert not t.FROM_STATE.isin(["PAID-OFF", "CHARGE-OFF"]).any()


def test_first_activation_is_not_a_roll(fixture_db) -> None:
    t = fixture_db.execute("SELECT * FROM transitions WHERE ID = 1001").df()
    assert t.ORIGIN_MONTH.min() == -7  # leading X months are not origins


def test_sql_transitions_reconcile_with_pandas(synthetic_db, params) -> None:
    con, credit = synthetic_db
    panel = fe.reference_panel(credit, params["mob_bands"])
    ref = fe.reference_transitions(panel)
    sql = con.execute("SELECT * FROM transitions").df()
    assert len(ref) == len(sql)
    rc = ref.groupby(["FROM_STATE", "TO_STATE"]).size().rename("n").reset_index()
    sc = con.execute(
        "SELECT FROM_STATE, TO_STATE, n FROM roll_counts WHERE SLICE_TYPE = 'overall'"
    ).df()
    assert np.array_equal(counts_from_long(rc), counts_from_long(sc))
    band_ref = ref.groupby("MOB_BAND").size().sort_index()
    band_sql = sql.groupby("MOB_BAND").size().sort_index()
    assert band_ref.equals(band_sql)


def test_sql_panel_reconciles_with_pandas(synthetic_db, params) -> None:
    con, credit = synthetic_db
    ref = (
        fe.reference_panel(credit, params["mob_bands"])
        .set_index(["ID", "MONTHS_BALANCE"])
        .sort_index()
    )
    sql = con.execute("SELECT * FROM panel").df().set_index(["ID", "MONTHS_BALANCE"]).sort_index()
    assert len(ref) == len(sql)
    assert (ref.STATE == sql.STATE).all()
    assert np.allclose(ref.MOB.fillna(-1), sql.MOB.astype(float).fillna(-1))
    assert (ref.RECORD_MOB == sql.RECORD_MOB).all()


def test_sql_named_rolls_reconcile_with_python(synthetic_db) -> None:
    from src.analytics.roll_rates import named_metrics

    con, _ = synthetic_db
    sc = con.execute(
        "SELECT FROM_STATE, TO_STATE, n FROM roll_counts WHERE SLICE_TYPE = 'overall'"
    ).df()
    py = named_metrics(counts_from_long(sc))
    nr = con.execute("SELECT METRIC, NUM, DEN FROM named_rolls WHERE SLICE_TYPE = 'overall'").df()
    for r in nr.itertuples(index=False):
        num, den = py[r.METRIC]
        assert float(num) == float(r.NUM if r.NUM == r.NUM else 0)
        assert float(den) == float(r.DEN)
