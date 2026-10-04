"""Read access to the precomputed artefacts for the services layer.

Deploy mode (default) reads only the committed aggregated cubes, ``reports/results.json`` and
``reports/dq_report.json``. Local mode additionally rebuilds every artefact from the raw files
when a cube is missing. Loaders are cached with ``st.cache_data`` keyed on the file path and
its modification time, so a rebuilt cube is picked up without restarting the app.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from src.utils.helpers import (
    CUBES_DIR,
    DQ_REPORT_PATH,
    PROCESSED_DIR,
    RESULTS_PATH,
    data_mode,
    read_json,
)
from src.utils.logging import get_logger

log = get_logger("store")


class ArtefactMissingError(FileNotFoundError):
    """A precomputed artefact is missing in deploy mode."""


@st.cache_data(show_spinner=False)
def _read_parquet(path: str, mtime: float) -> pd.DataFrame:
    return pd.read_parquet(path)


@st.cache_data(show_spinner=False)
def _read_json(path: str, mtime: float) -> Any:
    return read_json(Path(path))


def _ensure(path: Path) -> None:
    if path.exists():
        return
    if data_mode() == "local":
        from src import pipeline

        log.info("artefact %s missing; rebuilding from raw files (local mode)", path.name)
        pipeline.run("all")
        if path.exists():
            return
    raise ArtefactMissingError(
        f"{path.name} not found. Run `make build` with the Kaggle files in data/raw/ (local mode)."
    )


def cube(name: str) -> pd.DataFrame:
    """Aggregated cube ``data/processed/cubes/<name>.parquet``."""
    path = CUBES_DIR / f"{name}.parquet"
    _ensure(path)
    return _read_parquet(str(path), path.stat().st_mtime)


def backtest_results() -> pd.DataFrame:
    """Backtest table ``data/processed/backtest_results.parquet``."""
    path = PROCESSED_DIR / "backtest_results.parquet"
    _ensure(path)
    return _read_parquet(str(path), path.stat().st_mtime)


def results() -> dict[str, Any]:
    """``reports/results.json``."""
    _ensure(RESULTS_PATH)
    return _read_json(str(RESULTS_PATH), RESULTS_PATH.stat().st_mtime)


def dq_report() -> dict[str, Any]:
    """``reports/dq_report.json``."""
    _ensure(DQ_REPORT_PATH)
    return _read_json(str(DQ_REPORT_PATH), DQ_REPORT_PATH.stat().st_mtime)


def display(key: str) -> Any:
    """Raw value of a display key in results.json (None if absent)."""
    item = results().get("display", {}).get(key)
    return None if item is None else item.get("value")
