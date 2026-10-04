"""Global filter definitions shared by the services (cube dimensions only)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.utils.helpers import vintage_qtr_label

VINTAGE_GROUPS: dict[str, list[int]] = {
    "All vintages": list(range(21)),
    "Opened M-60 to M-49": [0, 1, 2, 3],
    "Opened M-48 to M-37": [4, 5, 6, 7],
    "Opened M-36 to M-25": [8, 9, 10, 11],
    "Opened M-24 to M-13": [12, 13, 14, 15],
    "Opened M-12 to M0": [16, 17, 18, 19, 20],
}
ALL_BANDS = "All MOB bands"
ALL_SEGMENTS = "All clients"
COMPARE_OPTIONS = {"vs 1M earlier": 1, "vs 3M earlier": 3, "vs 12M earlier": 12}


@dataclass(frozen=True)
class Filters:
    """Active global filters."""

    as_of: int = 0
    compare: int = 1
    mob_band: str = ALL_BANDS
    vintage_group: str = "All vintages"
    segment: str = ALL_SEGMENTS

    @property
    def segment_active(self) -> bool:
        """True when an age or income segment is selected."""
        return self.segment != ALL_SEGMENTS

    @property
    def dims_active(self) -> bool:
        """True when a MOB-band or vintage filter is set."""
        return self.mob_band != ALL_BANDS or self.vintage_group != "All vintages"

    @property
    def any_active(self) -> bool:
        """True when any filter differs from its default."""
        return self != Filters()

    def segment_key(self) -> tuple[str, str] | None:
        """(SEG_TYPE, SEGMENT) of the selected segment or None."""
        if not self.segment_active:
            return None
        kind, label = self.segment.split(": ", 1)
        return ("age_band" if kind == "Age" else "income_band", label)


def segment_options(age_labels: list[str], income_labels: list[str]) -> list[str]:
    """Options for the segment filter."""
    return (
        [ALL_SEGMENTS] + [f"Age: {a}" for a in age_labels] + [f"Income: {i}" for i in income_labels]
    )


def apply_dims(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Filter a cube with MOB_BAND / VINTAGE_QTR columns by the active dimension filters."""
    out = df
    if f.mob_band != ALL_BANDS and "MOB_BAND" in out:
        out = out[f.mob_band == out.MOB_BAND]
    if f.vintage_group != "All vintages" and "VINTAGE_QTR" in out:
        out = out[out.VINTAGE_QTR.isin(VINTAGE_GROUPS[f.vintage_group])]
    return out


def vintage_group_quarters(name: str) -> list[str]:
    """Quarter labels of a vintage group."""
    return [vintage_qtr_label(q) for q in VINTAGE_GROUPS[name]]
