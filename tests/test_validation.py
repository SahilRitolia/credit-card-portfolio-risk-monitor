"""Data-quality rules and the file-truncation test on synthetic metric dictionaries."""

from src.data import validation


def _metrics(**over) -> dict:
    m = {
        "max_credit_id": 100.0,
        "app_ids_above_max_credit_id": 50.0,
        "matched_above_max_credit_id": 0.0,
        "app_ids_at_or_below_max_credit_id": 80.0,
        "matched_at_or_below_max_credit_id": 80.0,
        "max_credit_id_records": 5.0,
        "max_credit_id_first_month": -4.0,
        "max_credit_id_first_status_is_c": 1.0,
        "first_status_c_clients": 1.0,
        "credit_clients": 100.0,
    }
    m.update(over)
    return m


def test_truncation_fires_on_limit_and_hard_cut(params) -> None:
    limit = params["truncation"]["excel_row_limit"]
    r = validation.file_truncation_test(limit, "100", _metrics(), params)
    assert r["fired"] and r["excluded"]


def test_truncation_does_not_fire_below_limit(params) -> None:
    r = validation.file_truncation_test(1000, "100", _metrics(), params)
    assert not r["fired"]


def test_truncation_does_not_fire_without_hard_cut(params) -> None:
    limit = params["truncation"]["excel_row_limit"]
    r = validation.file_truncation_test(
        limit, "100", _metrics(matched_above_max_credit_id=3.0), params
    )
    assert not r["fired"]


def test_pilot_reconciliation_flags_differences(params) -> None:
    rows = validation.reconcile_pilot(
        {"credit_rows": params["pilot_targets"]["credit_rows"] + 10_000}, params
    )
    assert rows and not rows[0]["agrees"]
    rows = validation.reconcile_pilot(
        {"credit_rows": params["pilot_targets"]["credit_rows"]}, params
    )
    assert rows[0]["agrees"]


def test_fixture_dq_metrics(fixture_db) -> None:
    from src.data import sql_runner

    m = sql_runner.metrics_dict(fixture_db)
    assert m["credit_dup_id_month"] == 0
    assert m["month_single_gap_pairs"] == 2 and m["month_multi_gap_pairs"] == 1
    assert m["x_only_clients"] == 1
    assert m["co_to_nonco_consecutive_nonx"] == 1 and m["co_to_c"] == 1
    assert m["app_duplicated_ids"] == 2
    assert m["application_only"] == 1  # ID 9999
    dup = fixture_db.execute(
        "SELECT ID, HAS_CONFLICT FROM app_dedup WHERE IS_DUPLICATE_ID ORDER BY ID"
    ).df()
    assert list(zip(dup.ID, dup.HAS_CONFLICT, strict=True)) == [(1002, True), (1008, False)]
    seg = fixture_db.execute("SELECT * FROM client_segments WHERE ID = 1002").df()
    assert seg.AGE_BAND.isna().all()  # conflicting duplicates excluded from segmentation
    sentinel = fixture_db.execute("SELECT DAYS_EMPLOYED FROM app_clean WHERE ID = 1004").fetchone()[
        0
    ]
    assert sentinel is None


def test_cleaning_reference_matches_sql(fixture_db) -> None:
    import pandas as pd

    from src.data import cleaning
    from tests.conftest import FIXTURES

    app = pd.read_csv(FIXTURES / "application_fixture.csv")
    ref = cleaning.clean_applications(app).set_index("ID").sort_index()
    sql = fixture_db.execute("SELECT * FROM app_clean").df().set_index("ID").sort_index()
    assert (ref.HAS_CONFLICT == sql.HAS_CONFLICT).all()
    assert (ref.IS_DUPLICATE_ID == sql.IS_DUPLICATE_ID).all()
    assert ((ref.AGE_YEARS - sql.AGE_YEARS).abs() < 1e-9).all()
