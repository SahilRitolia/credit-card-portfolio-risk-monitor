"""State mapping under both modes, state classes and invalid status handling."""

import pandas as pd
import pytest

from src.data import feature_engineering as fe
from src.data import sql_runner
from src.utils import constants as C


def test_evidence_mapping_every_raw_status() -> None:
    raw = pd.Series(["0", "1", "2", "3", "4", "5", "C", "X"])
    got = fe.map_states(raw, "evidence_based").tolist()
    assert got == [C.B0, C.B1, C.B2, C.B3, C.B4, C.CHARGE_OFF, C.PAID_OFF, C.DORMANT]


def test_literal_mapping_every_raw_status() -> None:
    raw = pd.Series(["0", "1", "2", "3", "4", "5", "C", "X"])
    got = fe.map_states(raw, "source_literal").tolist()
    assert got[-2:] == ["CURRENT", "OUTSIDE"]
    assert got[:6] == [C.B0, C.B1, C.B2, C.B3, C.B4, C.CHARGE_OFF]


def test_invalid_status_is_not_mapped() -> None:
    got = fe.map_states(pd.Series(["7", "", "c"]), "evidence_based")
    assert got.iloc[0] != got.iloc[0]  # NaN
    assert got.iloc[2] == C.PAID_OFF  # case-insensitive


def test_unknown_mapping_mode_raises() -> None:
    with pytest.raises(ValueError):
        fe.map_states(pd.Series(["0"]), "other")


def test_classes() -> None:
    assert C.STATE_CLASS[C.DORMANT].startswith("transient")
    assert C.STATE_CLASS[C.PAID_OFF] == "absorbing exit"
    assert C.STATE_CLASS[C.CHARGE_OFF] == "absorbing"
    assert C.ABSORBING == [C.PAID_OFF, C.CHARGE_OFF]


def test_sql_status_lookup_matches_constants(fixture_db) -> None:
    lk = fixture_db.execute(
        "SELECT RAW_STATUS, STATE, STATE_LITERAL, IS_OPEN, IS_30P FROM status_lookup"
    ).df()
    for r in lk.itertuples(index=False):
        assert C.EVIDENCE_MAPPING[r.RAW_STATUS] == r.STATE
        assert C.LITERAL_MAPPING[r.RAW_STATUS] == r.STATE_LITERAL
        assert bool(r.IS_OPEN) == (r.STATE in C.OPEN_STATES)
        assert bool(r.IS_30P) == (r.STATE in C.DPD30_STATES)


def test_pipeline_refuses_source_literal(params) -> None:
    p = dict(params, STATE_MAPPING="source_literal")
    with pytest.raises(ValueError):
        sql_runner.template_context(p)


def test_missing_template_slot_raises() -> None:
    with pytest.raises(KeyError):
        sql_runner.render("SELECT {{NOT_A_SLOT}}", {})
