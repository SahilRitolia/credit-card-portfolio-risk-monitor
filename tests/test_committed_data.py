"""Committed artefacts are aggregated only: no identifier columns, small files, suppression."""

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from src.utils.helpers import CUBES_DIR, PROCESSED_DIR, RESULTS_PATH

FORBIDDEN = {"ID", "CLIENT_ID", "client_id", "id"}
CUBES = sorted(CUBES_DIR.glob("*.parquet")) + [PROCESSED_DIR / "backtest_results.parquet"]


def test_cubes_exist() -> None:
    assert len(CUBES) > 20 and RESULTS_PATH.exists()


@pytest.mark.parametrize("path", CUBES, ids=lambda p: Path(p).name)
def test_no_identifier_columns_and_size(path: Path) -> None:
    assert not FORBIDDEN & set(pq.read_schema(path).names)
    assert path.stat().st_size < 25 * 1024 * 1024


@pytest.mark.parametrize(
    "name", ["segment_stock_cube", "segment_transition_cube", "segment_transition_rows"]
)
def test_segment_cubes_suppress_small_cells(name: str, params) -> None:
    df = pd.read_parquet(CUBES_DIR / f"{name}.parquet")
    k = params["suppress_cube_n"]
    shown = df.n.dropna()
    assert (shown >= k).all()
    assert df.loc[df.suppressed, "n"].isna().all()


def test_segment_roll_cells_suppressed() -> None:
    rm = pd.read_parquet(CUBES_DIR / "roll_matrices.parquet")
    seg = rm[rm.SLICE_TYPE.isin(["age_band", "income_band"])]
    assert (seg.n.dropna() >= 5).all()
