"""Client-level bootstrap, vectorised through per-client sufficient statistics.

The resampling unit is the client (``ID``): a replicate draws n clients with replacement and
keeps each client's whole history. Because every metric in this project is a function of
counts that are sums over clients, a replicate is a multinomial weight vector ``w`` over
clients and its counts are ``w @ S`` where ``S`` (clients x statistics) holds each client's
contribution. No history is reconstructed in a loop.

The point estimate uses ``w = 1`` and therefore goes through exactly the same code path.
``S`` is stored as a SciPy sparse matrix (docs/decisions.md D-011): most clients contribute
to few cells, and a dense S would not fit in a laptop's memory.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import sparse

from src.utils.logging import get_logger

log = get_logger("bootstrap")


@dataclass
class StatRegistry:
    """Named blocks of columns in the client statistic matrix."""

    n_clients: int
    blocks: dict[str, tuple[int, tuple[int, ...]]] = field(default_factory=dict)
    _rows: list[np.ndarray] = field(default_factory=list)
    _cols: list[np.ndarray] = field(default_factory=list)
    _vals: list[np.ndarray] = field(default_factory=list)
    n_cols: int = 0

    def add(self, name: str, shape: tuple[int, ...], client_idx, flat_idx, values=None) -> None:
        """Register a block of ``prod(shape)`` columns and add contributions.

        ``client_idx`` and ``flat_idx`` (position inside the block) are equal-length arrays;
        duplicates are summed. ``values`` defaults to 1.
        """
        if name in self.blocks:
            raise KeyError(f"block {name} already registered")
        size = int(np.prod(shape))
        offset = self.n_cols
        self.blocks[name] = (offset, tuple(shape))
        self.n_cols += size
        ci = np.asarray(client_idx, dtype=np.int64)
        fi = np.asarray(flat_idx, dtype=np.int64)
        if len(ci):
            if fi.min() < 0 or fi.max() >= size:
                raise IndexError(f"block {name}: flat index outside 0..{size - 1}")
            if ci.min() < 0 or ci.max() >= self.n_clients:
                raise IndexError(f"block {name}: client index outside range")
        v = np.ones(len(ci)) if values is None else np.asarray(values, dtype=float)
        self._rows.append(ci)
        self._cols.append(fi + offset)
        self._vals.append(v)

    def matrix(self) -> sparse.csr_matrix:
        """The (clients x columns) sparse statistic matrix."""
        rows = np.concatenate(self._rows) if self._rows else np.zeros(0, dtype=np.int64)
        cols = np.concatenate(self._cols) if self._cols else np.zeros(0, dtype=np.int64)
        vals = np.concatenate(self._vals) if self._vals else np.zeros(0)
        return sparse.csr_matrix((vals, (rows, cols)), shape=(self.n_clients, self.n_cols))

    def take(self, R: np.ndarray, name: str) -> np.ndarray:
        """Slice block ``name`` from replicate sums ``R`` (B x K) and reshape to (B, *shape)."""
        offset, shape = self.blocks[name]
        size = int(np.prod(shape))
        return R[:, offset : offset + size].reshape((R.shape[0],) + shape)


def replicate_weights(n: int, B: int, seed: int, chunk: int) -> Iterator[np.ndarray]:
    """Yield (b x n) float32 multinomial client weights, chunk by chunk, reproducibly.

    Each replicate draws ``n`` client indices with replacement; the weight of a client is
    the number of times it was drawn.
    """
    rng = np.random.default_rng(seed)
    done = 0
    while done < B:
        b = min(chunk, B - done)
        W = np.empty((b, n), dtype=np.float32)
        for r in range(b):
            W[r] = np.bincount(rng.integers(0, n, size=n), minlength=n)
        done += b
        yield W


def run(S: sparse.csr_matrix, B: int, seed: int, chunk: int) -> np.ndarray:
    """Replicate column sums ``W @ S`` for ``B`` replicates (returns B x K float64)."""
    n, K = S.shape
    out = np.empty((B, K), dtype=np.float64)
    ST = S.T.tocsr().astype(np.float32)
    i = 0
    for W in replicate_weights(n, B, seed, chunk):
        out[i : i + W.shape[0]] = np.asarray(ST @ W.T).T
        i += W.shape[0]
        log.info("bootstrap replicates %d/%d", i, B)
    return out


def point(S: sparse.csr_matrix) -> np.ndarray:
    """Column sums with unit weights (the point estimate), shape (1, K)."""
    return np.asarray(S.sum(axis=0)).reshape(1, -1).astype(np.float64)


def summarise(
    samples: np.ndarray, level: float = 0.95, zero_share_flag: float = 0.5
) -> dict[str, np.ndarray]:
    """Percentile interval, bootstrap SE and degeneracy flag along axis 0.

    A cell is degenerate when at least ``zero_share_flag`` of its replicates are exactly 0:
    the lower percentile is then 0 by construction and the interval should be reported as an
    upper bound (``hi``) rather than [0, hi].
    """
    a = (1.0 - level) / 2.0
    s = np.asarray(samples, dtype=float)
    with np.errstate(invalid="ignore"):
        lo = np.nanquantile(s, a, axis=0)
        hi = np.nanquantile(s, 1.0 - a, axis=0)
        se = np.nanstd(s, axis=0, ddof=1)
        zero = np.mean(s == 0.0, axis=0)
    return {"lo": lo, "hi": hi, "se": se, "zero_share": zero, "degenerate": zero >= zero_share_flag}


def materialise_replicate(
    panel: pd.DataFrame, counts: np.ndarray, client_ids: np.ndarray, id_col: str = "ID"
) -> pd.DataFrame:
    """Build the resampled panel for one replicate (used to test history integrity).

    Client ``client_ids[i]`` appears ``counts[i]`` times, each copy with its complete history
    and a new replicate key ``REP_ID``.
    """
    pieces = []
    rep = 0
    groups = dict(tuple(panel.groupby(id_col, sort=False)))
    for cid, k in zip(client_ids, counts, strict=True):
        for _ in range(int(k)):
            g = groups[cid].copy()
            g["REP_ID"] = rep
            pieces.append(g)
            rep += 1
    if not pieces:
        return panel.iloc[0:0].assign(REP_ID=pd.Series(dtype=int))
    return pd.concat(pieces, ignore_index=True)
