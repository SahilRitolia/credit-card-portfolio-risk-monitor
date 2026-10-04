"""Client-level bootstrap: intact histories, reproducibility, intervals, degeneracy."""

import numpy as np
import pandas as pd

from src.models import bootstrap


def _panel() -> pd.DataFrame:
    rows = []
    for cid in range(20):
        for m in range(cid % 5 + 2):
            rows.append({"ID": 500 + cid, "MONTH": m, "SIG": f"{500 + cid}-{m}"})
    return pd.DataFrame(rows)


def test_replicates_keep_client_histories_intact() -> None:
    panel = _panel()
    ids = panel.ID.unique()
    W = next(bootstrap.replicate_weights(len(ids), 3, seed=11, chunk=3))
    for w in W:
        rep = bootstrap.materialise_replicate(panel, w, ids)
        assert len(rep.REP_ID.unique()) == int(w.sum()) == len(ids)
        for _, g in rep.groupby("REP_ID"):
            cid = g.ID.iloc[0]
            orig = panel[cid == panel.ID]
            assert g.ID.nunique() == 1
            assert list(g.SIG) == list(orig.SIG)  # full, ordered history of one client


def test_weighted_sums_equal_materialised_replicate_statistics() -> None:
    panel = _panel()
    ids = panel.ID.unique()
    reg = bootstrap.StatRegistry(n_clients=len(ids))
    pos = pd.Series(np.arange(len(ids)), index=ids)
    reg.add("months", (6,), pos.loc[panel.ID].to_numpy(), panel.MONTH.to_numpy())
    S = reg.matrix()
    W = next(bootstrap.replicate_weights(len(ids), 1, seed=3, chunk=1))
    R = np.asarray(S.T @ W[0])
    rep = bootstrap.materialise_replicate(panel, W[0], ids)
    direct = np.bincount(rep.MONTH, minlength=6)
    assert np.allclose(R, direct)


def test_seed_reproducibility() -> None:
    reg = bootstrap.StatRegistry(n_clients=50)
    reg.add("x", (2,), np.arange(50), np.arange(50) % 2)
    S = reg.matrix()
    a = bootstrap.run(S, 40, seed=9, chunk=15)
    b = bootstrap.run(S, 40, seed=9, chunk=15)
    c = bootstrap.run(S, 40, seed=10, chunk=15)
    assert np.array_equal(a, b) and not np.array_equal(a, c)
    assert np.allclose(a.sum(axis=1), 50)  # n clients drawn per replicate
    assert np.allclose(bootstrap.point(S), [[25, 25]])


def test_percentile_interval_on_known_distribution() -> None:
    s = np.random.default_rng(0).normal(0, 1, size=(200_000, 1))
    out = bootstrap.summarise(s)
    assert abs(out["lo"][0] + 1.96) < 0.02 and abs(out["hi"][0] - 1.96) < 0.02
    assert abs(out["se"][0] - 1.0) < 0.01


def test_degenerate_cells_are_flagged() -> None:
    s = np.zeros((1000, 1))
    s[:100] = 0.01
    out = bootstrap.summarise(s)
    assert bool(out["degenerate"][0]) and out["lo"][0] == 0


def test_registry_rejects_out_of_range_indices() -> None:
    import pytest

    reg = bootstrap.StatRegistry(n_clients=2)
    with pytest.raises(IndexError):
        reg.add("x", (2,), [0], [5])
