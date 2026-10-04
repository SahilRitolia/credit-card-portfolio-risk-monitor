"""Locate the Kaggle files and register them in an in-process DuckDB database.

The two CSVs (or the Kaggle zip that contains them) are searched for in, in order:
``$CCRM_RAW_DIR``, ``data/raw/``, the working directory and any ``uploads`` directory
that the execution environment mounts under ``/mnt``. Nothing is synthesised: if the
files are not found, :class:`RawDataNotFoundError` is raised and the build stops.
"""

from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from src.utils.helpers import ROOT
from src.utils.logging import get_logger

log = get_logger("ingestion")

APP_FILE = "application_record.csv"
CREDIT_FILE = "credit_record.csv"


class RawDataNotFoundError(FileNotFoundError):
    """Raised when neither the two CSVs nor the Kaggle zip can be found."""


@dataclass(frozen=True)
class RawSource:
    """Where the raw data was found and how to read it."""

    kind: str  # "csv" or "zip"
    application: Path
    credit: Path
    zip_path: Path | None = None

    def describe(self) -> str:
        """Short description safe to log (relative path when inside the repo)."""
        target = self.zip_path or self.credit.parent
        try:
            return f"{self.kind}: {target.resolve().relative_to(ROOT)}"
        except ValueError:
            return f"{self.kind}: {target.name}"


def candidate_dirs() -> list[Path]:
    """Directories searched for raw files, highest priority first."""
    dirs: list[Path] = []
    env = os.environ.get("CCRM_RAW_DIR")
    if env:
        p = Path(env)
        dirs.append(p if p.is_absolute() else ROOT / p)
    dirs += [ROOT / "data" / "raw", Path.cwd()]
    mnt = Path("/mnt")
    if mnt.is_dir():
        dirs += sorted(p for p in mnt.glob("*/uploads") if p.is_dir())
    seen: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.append(d)
    return seen


def _zip_has_both(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = {Path(n).name for n in zf.namelist()}
    except zipfile.BadZipFile:
        return False
    return {APP_FILE, CREDIT_FILE} <= names


def locate_raw(dirs: list[Path] | None = None) -> RawSource:
    """Find the raw CSVs or a zip containing both; raise if absent."""
    for d in dirs or candidate_dirs():
        if not d.is_dir():
            continue
        app, credit = d / APP_FILE, d / CREDIT_FILE
        if app.is_file() and credit.is_file():
            return RawSource("csv", app, credit)
        for z in sorted(d.glob("*.zip")):
            if _zip_has_both(z):
                return RawSource("zip", Path(APP_FILE), Path(CREDIT_FILE), zip_path=z)
    raise RawDataNotFoundError(
        "Kaggle files not found. Put application_record.csv and credit_record.csv (or the "
        "Kaggle zip) in data/raw/ or set CCRM_RAW_DIR. See data/README.md."
    )


def _read_zip_member(zip_path: Path, name: str) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        member = next(n for n in zf.namelist() if Path(n).name == name)
        with zf.open(member) as fh:
            return pd.read_csv(io.TextIOWrapper(fh, encoding="utf-8"), dtype=str)


def register_sources(con: duckdb.DuckDBPyConnection, source: RawSource) -> None:
    """Create ``src_application`` and ``src_credit`` (all VARCHAR) in ``con``.

    CSVs are scanned lazily by DuckDB; zip members are read by pandas and registered.
    Typing happens in ``sql/01_schema.sql`` so invalid values surface as data-quality
    findings rather than load errors.
    """
    if source.kind == "csv":
        for view, path in (("src_application", source.application), ("src_credit", source.credit)):
            con.execute(
                f"CREATE OR REPLACE VIEW {view} AS "
                f"SELECT * FROM read_csv('{path.as_posix()}', all_varchar = true, header = true)"
            )
    else:
        assert source.zip_path is not None
        for view, name in (("src_application", APP_FILE), ("src_credit", CREDIT_FILE)):
            df = _read_zip_member(source.zip_path, name)
            con.register(f"{view}_df", df)
            con.execute(f"CREATE OR REPLACE VIEW {view} AS SELECT * FROM {view}_df")
    log.info("registered raw sources (%s)", source.describe())


def final_client_in_file_order(source: RawSource) -> tuple[str | None, int]:
    """Return (ID of the last data row, number of data rows) of credit_record.csv."""
    if source.kind == "csv":
        n = 0
        last = None
        with open(source.credit, "rb") as fh:
            next(fh, None)
            for line in fh:
                if line.strip():
                    n += 1
                    last = line
        last_id = last.decode().split(",")[0].strip() if last else None
        return last_id, n
    assert source.zip_path is not None
    df = _read_zip_member(source.zip_path, CREDIT_FILE)
    return (str(df["ID"].iloc[-1]) if len(df) else None), len(df)


def connect(
    source: RawSource | None = None, database: str = ":memory:"
) -> duckdb.DuckDBPyConnection:
    """Open a DuckDB connection with the raw sources registered."""
    con = duckdb.connect(database)
    con.execute("SET preserve_insertion_order = true")
    register_sources(con, source or locate_raw())
    return con
