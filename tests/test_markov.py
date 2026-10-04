"""Markov chain, absorbing analytics, no-leakage and the MOB-conditioned forecast."""

import numpy as np
import pytest

from src.models import absorbing, backtesting, markov, mob_transition
from src.models.markov import IDX, N_STATES
from src.utils import constants as C


def _counts(seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).integers(1, 200, size=(6, 8)).astype(float)


def test_matrix_dimensions_row_sums_and_absorbing_identity() -> None:
    P = markov.estimate(_counts())
    assert P.shape == (8, 8)
    assert markov.row_sums_ok(P)
    assert np.allclose(P[6:], np.eye(8)[6:])


def test_view_b_drops_dormant_destination() -> None:
    P = markov.estimate(_counts(), drop_dormant_dest=True)
    assert np.allclose(P[:6, IDX[C.DORMANT]], 0)
    assert np.allclose(P.sum(axis=1), 1.0)


def test_empty_row_stays_in_place() -> None:
    c = _counts()
    c[IDX[C.B4]] = 0
    P = markov.estimate(c)
    assert P[IDX[C.B4], IDX[C.B4]] == 1.0
    assert markov.empty_rows(c) == [C.B4]


def test_forecast_matches_hand_calculation() -> None:
    P = markov.estimate(_counts(3))
    pi = np.zeros(N_STATES)
    pi[IDX[C.B1]] = 100
    hand = pi @ P @ P @ P
    assert np.allclose(markov.forecast(pi, P, 3), hand)
    assert np.isclose(markov.forecast(pi, P, 3).sum(), 100)


def test_fundamental_matrix_two_state_example() -> None:
    Q = np.array([[0.5, 0.2], [0.1, 0.6]])
    N = absorbing.fundamental_matrix(Q)
    assert np.allclose(N, np.linalg.inv(np.eye(2) - Q))
    # expected visits from state 0: solve by hand (I-Q)N = I
    assert np.allclose((np.eye(2) - Q) @ N, np.eye(2))


def test_absorption_probabilities_sum_to_one() -> None:
    P = markov.estimate(_counts(5))
    for inc in (True, False):
        r = absorbing.analyse(P, inc)
        assert np.allclose(r.p_chargeoff + r.p_paidoff, 1.0)
        assert np.all(r.months_to_resolution >= 1.0)


def test_point_of_no_return_is_first_bucket_where_co_dominates() -> None:
    c = np.zeros((6, 8))
    c[IDX[C.DORMANT], IDX[C.B0]] = 10
    for b, co, po in ((C.B0, 1, 9), (C.B1, 2, 8), (C.B2, 3, 7), (C.B3, 8, 2), (C.B4, 9, 1)):
        c[IDX[b], IDX[C.CHARGE_OFF]] = co
        c[IDX[b], IDX[C.PAID_OFF]] = po
    r = absorbing.analyse(markov.estimate(c))
    assert absorbing.point_of_no_return(r) == C.B3


def test_no_leakage_training_uses_only_destinations_up_to_origin() -> None:
    dm = np.zeros((60, 6, 8))
    dm[:, IDX[C.B0], IDX[C.B0]] = 100  # stable history
    t0 = -12
    future = t0 + 59 + 1  # destination month t0 + 1
    dm[future:, IDX[C.B0], IDX[C.CHARGE_OFF]] = 1000  # a future regime change
    train = backtesting.training_counts(dm, t0)
    assert train[IDX[C.B0], IDX[C.CHARGE_OFF]] == 0
    P = markov.estimate(train)
    assert P[IDX[C.B0], IDX[C.CHARGE_OFF]] == 0
    full = backtesting.training_counts(dm, 0)
    assert full[IDX[C.B0], IDX[C.CHARGE_OFF]] > 0
    roll = backtesting.training_counts(dm, t0, window=24)
    assert roll.sum() == 24 * 100


def test_valid_origins_need_minimum_training(params) -> None:
    o = backtesting.valid_origins(params["backtest"])
    assert min(o) - (-59) + 1 >= params["backtest"]["min_train_months"]
    assert max(o) <= params["backtest"]["origin_end"]


def test_errors_and_skill() -> None:
    a = np.full((1, 8), 1 / 8)
    e = backtesting.errors(a, a)
    assert e["mae_pp"][0] == 0 and e["rmse_pp"][0] == 0
    assert backtesting.skill(np.array([1.0]), np.array([4.0]))[0] == pytest.approx(0.75)


def test_mob_forecast_applies_band_matrices_in_sequence() -> None:
    bands = [{"label": "early", "lo": 0, "hi": 1}, {"label": "late", "lo": 2, "hi": 60}]
    early = np.eye(8)
    late = np.eye(8)
    early[IDX[C.B0]] = 0
    early[IDX[C.B0], IDX[C.B1]] = 1.0  # early: 1-29 -> 30-59
    late[IDX[C.B1]] = 0
    late[IDX[C.B1], IDX[C.PAID_OFF]] = 1.0  # late: 30-59 -> paid-off
    band_P = np.stack([early, late])
    coh = np.zeros((61, 6))
    coh[1, IDX[C.B0]] = 10  # MOB 1 at origin: step 1 uses early (MOB 1), step 2 uses late (MOB 2)
    d = mob_transition.mob_forecast(coh, band_P, 2, bands)
    assert d[IDX[C.PAID_OFF]] == 10
    reused = np.zeros(8) + 0
    pi = np.zeros(8)
    pi[IDX[C.B0]] = 10
    reused = pi @ early @ early  # what a forecast that reused the origin band would give
    assert reused[IDX[C.B1]] == 10 and d[IDX[C.B1]] == 0


def test_dirichlet_alpha_is_tuned_on_validation_likelihood() -> None:
    rng = np.random.default_rng(1)
    fit = rng.integers(0, 50, (3, 6, 8)).astype(float)
    val = rng.integers(0, 50, (3, 6, 8)).astype(float)
    a, scores = mob_transition.tune_alpha(fit, fit.sum(0), val, [0, 1, 10, 100])
    assert a in scores and scores[a] == max(scores.values())
