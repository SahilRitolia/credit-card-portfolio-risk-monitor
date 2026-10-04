"""Services layer reads cubes only and reproduces results.json values."""

import numpy as np
import pytest

from src.services import overview, rolls, store, stress
from src.services.filters import Filters


def test_overview_kpis_match_results() -> None:
    cards = {c["label"]: c for c in overview.kpis(Filters())}
    assert cards["OPEN ACCOUNTS"]["value"] == store.display("open_m0")
    assert cards["30+ DPD"]["value"] == pytest.approx(store.display("prev30_m0"))
    assert cards["30+ DPD"]["ci"] is not None


def test_filtered_kpis_have_no_bootstrap_interval() -> None:
    cards = {c["label"]: c for c in overview.kpis(Filters(mob_band="early 0-6"))}
    assert cards["30+ DPD"]["ci"] is None


def test_matrix_rows_sum_to_one() -> None:
    t = rolls.matrix("Full window", "A", Filters())["table"]
    s = t[~t.suppressed].groupby("FROM_STATE").p.sum()
    assert np.allclose(s, 1.0)
    t = rolls.matrix(
        "Last 12 months", "B", Filters(mob_band="early 0-6", vintage_group="Opened M-24 to M-13")
    )
    tb = t["table"]
    assert t["interval"] is None
    assert np.allclose(tb[~tb.suppressed].groupby("FROM_STATE").p.sum(), 1.0)


def test_live_stress_base_matches_pipeline() -> None:
    r = stress.scenario(1.0, 0.0, 1000.0, 0.5, 12)
    assert r["el"] == pytest.approx(store.display("el12_base"), rel=1e-9)
    assert r["el_lo"] <= r["el"] <= r["el_hi"]
    assert r["incremental"] == pytest.approx(0.0)


def test_el_is_linear_in_ead_and_lgd() -> None:
    a = stress.scenario(1.5, -0.1, 1000.0, 0.5, 12)
    b = stress.scenario(1.5, -0.1, 2000.0, 0.25, 12)
    assert a["el"] == pytest.approx(b["el"])


def test_risk_signal_states() -> None:
    assert overview.risk_signal(Filters(as_of=-50))["status"] == "unavailable"
    r = overview.risk_signal(Filters(as_of=0))
    assert r["status"] in {"signal", "none"} and r["text"]


def test_waterfall_bridge_adds_up() -> None:
    w = overview.waterfall(Filters(as_of=-6))
    assert bool(w.check.iloc[0])
