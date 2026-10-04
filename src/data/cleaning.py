"""Application cleaning rules in pandas (reference for sql/03_cleaning.sql).

Rules: one row per ID; duplicated IDs flagged; when duplicates disagree on any attribute
the client's segment attributes are excluded; DAYS_EMPLOYED = 365243 is a sentinel and
becomes missing; age in years = -DAYS_BIRTH / 365.25; age bands from configuration;
income quartiles computed on matched, non-conflicting clients.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

EMPLOYED_SENTINEL = 365243
ATTRIBUTE_COLUMNS = [
    "CODE_GENDER",
    "FLAG_OWN_CAR",
    "FLAG_OWN_REALTY",
    "CNT_CHILDREN",
    "AMT_INCOME_TOTAL",
    "NAME_INCOME_TYPE",
    "NAME_EDUCATION_TYPE",
    "NAME_FAMILY_STATUS",
    "NAME_HOUSING_TYPE",
    "DAYS_BIRTH",
    "DAYS_EMPLOYED",
    "FLAG_WORK_PHONE",
    "FLAG_PHONE",
    "FLAG_EMAIL",
    "OCCUPATION_TYPE",
    "CNT_FAM_MEMBERS",
]


def dedupe_applications(app: pd.DataFrame) -> pd.DataFrame:
    """One row per ID with IS_DUPLICATE_ID and HAS_CONFLICT flags."""
    cols = [c for c in ATTRIBUTE_COLUMNS if c in app.columns]
    n_rows = app.groupby("ID").size().rename("n_rows")
    n_versions = app.drop_duplicates(["ID", *cols]).groupby("ID").size().rename("n_versions")
    out = app.drop_duplicates("ID").set_index("ID").join(n_rows).join(n_versions)
    out["IS_DUPLICATE_ID"] = out.n_rows > 1
    out["HAS_CONFLICT"] = out.n_versions > 1
    return out.drop(columns=["n_rows", "n_versions"]).reset_index()


def clean_applications(app: pd.DataFrame) -> pd.DataFrame:
    """Apply the sentinel rule and derive AGE_YEARS."""
    d = dedupe_applications(app)
    d["EMPLOYED_SENTINEL"] = d.DAYS_EMPLOYED == EMPLOYED_SENTINEL
    d["DAYS_EMPLOYED"] = d.DAYS_EMPLOYED.where(~d.EMPLOYED_SENTINEL)
    d["AGE_YEARS"] = -d.DAYS_BIRTH / 365.25
    return d


def age_band(age: pd.Series, bands: list[dict]) -> pd.Series:
    """Label ages with [lo, hi) bands from configuration (NaN outside every band)."""
    out = pd.Series(np.nan, index=age.index, dtype=object)
    for b in bands:
        out = out.mask((age >= b["lo"]) & (age < b["hi"]), b["label"])
    return out


def income_band(income: pd.Series, reference: pd.Series) -> pd.Series:
    """Quartile labels using thresholds computed on ``reference`` (matched clients)."""
    q25, q50, q75 = reference.quantile([0.25, 0.5, 0.75]).tolist()
    return pd.Series(
        np.select(
            [income <= q25, income <= q50, income <= q75, income.notna()],
            ["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"],
            default=None,
        ),
        index=income.index,
    ).replace({None: np.nan})
