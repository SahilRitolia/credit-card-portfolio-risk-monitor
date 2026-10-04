"""Paths, configuration loading and small I/O helpers shared by pipeline and app."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.utils.logging import get_logger

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "params.yaml"
SQL_DIR = ROOT / "sql"
PROCESSED_DIR = ROOT / "data" / "processed"
CUBES_DIR = PROCESSED_DIR / "cubes"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"
VALIDATION_DIR = REPORTS_DIR / "model_validation"
RESULTS_PATH = REPORTS_DIR / "results.json"
DQ_REPORT_PATH = REPORTS_DIR / "dq_report.json"
DOCS_DIR = ROOT / "docs"

log = get_logger("helpers")


def load_params(path: Path | None = None) -> dict[str, Any]:
    """Load ``config/params.yaml`` as a dict."""
    with open(path or CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def data_mode() -> str:
    """Return ``local`` or ``deploy`` from ``CCRM_DATA_MODE`` (default ``deploy``)."""
    mode = os.environ.get("CCRM_DATA_MODE", "deploy").strip().lower()
    if mode not in {"local", "deploy"}:
        raise ValueError(f"CCRM_DATA_MODE must be 'local' or 'deploy', got {mode!r}")
    return mode


def ensure_dirs() -> None:
    """Create the output directories used by the pipeline."""
    for d in (PROCESSED_DIR, CUBES_DIR, REPORTS_DIR, FIGURES_DIR, VALIDATION_DIR):
        d.mkdir(parents=True, exist_ok=True)


def to_jsonable(obj: Any) -> Any:
    """Convert numpy/pandas scalars and containers into plain JSON types."""
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if (np.isnan(v) or np.isinf(v)) else v
    if isinstance(obj, np.ndarray):
        return [to_jsonable(v) for v in obj.tolist()]
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def write_json(path: Path, payload: Any) -> None:
    """Write ``payload`` as pretty JSON with numpy types converted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(to_jsonable(payload), fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def read_json(path: Path) -> Any:
    """Read a JSON file."""
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a DataFrame to parquet without the index."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


@contextmanager
def timed(label: str) -> Iterator[None]:
    """Log the wall time of a block."""
    t0 = time.perf_counter()
    yield
    log.info("%s finished in %.1fs", label, time.perf_counter() - t0)


def rel_month_label(m: int) -> str:
    """Human label for a relative month index."""
    return "M0" if m == 0 else f"M{m}"


def vintage_qtr_label(idx: int) -> str:
    """Label of relative vintage quarter ``idx`` (0 = months -60..-58, 20 = month 0)."""
    lo = -60 + 3 * idx
    hi = min(lo + 2, 0)
    return f"M{lo}" if lo == hi else f"M{lo} to M{hi}"


def vintage_qtr_index(open_month: int) -> int:
    """Quarter index of an open month (relative)."""
    return (open_month + 60) // 3
