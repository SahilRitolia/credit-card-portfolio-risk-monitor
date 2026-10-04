"""Scenario transform and expected loss: hand example, row sums, monotonicity, reverse stress."""

import numpy as np
import pytest

from src.models import markov
from src.models.markov import IDX
from src.stress import expected_loss, scenarios
from src.utils import constants as C


def _P() -> np.ndarray:
    c = np.random.default_rng(4).integers(1, 100, (6, 8)).astype(float)
    c[:, IDX[C.CHARGE_OFF]] = 1  # rare charge-off as in the data
    return markov.estimate(c)


def test_hand_computed_el() -> None:
    P = np.eye(8)
    P[IDX[C.B1]] = 0
    P[IDX[C.B1], IDX[C.CHARGE_OFF]] = 0.2
    P[IDX[C.B1], IDX[C.B0]] = 0.8
    cohort = np.zeros(6)
    cohort[IDX[C.B1]] = 10
    cohort[IDX[C.DORMANT]] = 5
    el = expected_loss.expected_loss(P, cohort, 1, ead=1000, lgd=0.5)
    assert el[IDX[C.B1]] == pytest.approx(10 * 1000 * 0.2 * 0.5)
    assert el[IDX[C.DORMANT]] == 0  # DORMANT carries EAD 0 at origin
    el_d = expected_loss.expected_loss(P, cohort, 1, 1000, 0.5, include_dormant=True)
    assert el_d.sum() == pytest.approx(el.sum())  # dormant never charges off in this toy matrix
    assert expected_loss.pd_horizon(P, 12)[IDX[C.B1]] == pytest.approx(0.2)


@pytest.mark.parametrize("m", [0.0, 0.5, 1.0, 2.5, 10.0, 100.0])
@pytest.mark.parametrize("c", [-1.0, -0.5, 0.0, 0.5, 1.0])
def test_transform_keeps_rows_valid_at_extremes(m: float, c: float) -> None:
    Q = scenarios.stress_matrix(_P(), m, c)
    assert markov.row_sums_ok(Q)
    assert np.allclose(Q[6:], np.eye(8)[6:])


def test_base_scenario_is_identity_transform() -> None:
    P = _P()
    assert np.allclose(scenarios.stress_matrix(P, 1.0, 0.0), P)


def test_el_monotone_in_m_and_c() -> None:
    P = _P()
    coh = np.array([100, 800, 50, 10, 5, 3], dtype=float)
    ms = [0.5, 1, 1.5, 2, 3, 5, 10, 30]
    el_m = [expected_loss.scenario_el(P, coh, 12, m, 0.0, 1000, 0.5) for m in ms]
    assert all(b >= a - 1e-9 for a, b in zip(el_m, el_m[1:], strict=False))
    cs = [-1, -0.5, -0.25, 0, 0.25, 0.5, 1]
    el_c = [expected_loss.scenario_el(P, coh, 12, 1.5, c, 1000, 0.5) for c in cs]
    assert all(b <= a + 1e-9 for a, b in zip(el_c, el_c[1:], strict=False))


def test_reverse_stress_doubles_base_el() -> None:
    P = _P()
    coh = np.array([100, 800, 50, 10, 5, 3], dtype=float)
    m = float(expected_loss.reverse_stress_m(P, coh, 12, 2.0, 50.0))
    base = expected_loss.scenario_el(P, coh, 12, 1.0, 0.0, 1, 1)
    assert expected_loss.scenario_el(P, coh, 12, m, 0.0, 1, 1) == pytest.approx(2 * base, rel=1e-6)
    batch = expected_loss.reverse_stress_m(np.stack([P, P]), coh, 12, 2.0, 50.0)
    assert np.allclose(batch, m)


def test_invalid_parameters_raise() -> None:
    with pytest.raises(ValueError):
        scenarios.stress_matrix(_P(), -1.0, 0.0)
    with pytest.raises(ValueError):
        scenarios.stress_matrix(_P(), 1.0, 1.5)


def test_assumption_labels_present() -> None:
    assert "not observed in source data" in C.LABEL_EAD
    assert "not observed in source data" in C.LABEL_LGD
    assert "illustrative" in C.DISCLAIMER_EL
