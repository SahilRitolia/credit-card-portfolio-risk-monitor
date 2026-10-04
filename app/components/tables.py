"""Table rendering and CSV downloads."""

from __future__ import annotations

import pandas as pd
import streamlit as st


def show(
    df: pd.DataFrame,
    column_config: dict | None = None,
    height: int | str = "auto",
    key: str | None = None,
) -> None:
    """Render a table without the index."""
    st.dataframe(
        df, hide_index=True, column_config=column_config, height=height, key=key, width="stretch"
    )


def download_csv(df: pd.DataFrame, label: str, filename: str, key: str) -> None:
    """CSV download button for an already computed table."""
    st.download_button(
        label, df.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv", key=key
    )


def pct_col(label: str, help_text: str | None = None, d: int = 2) -> st.column_config.NumberColumn:
    """Column config for probabilities shown as percentages (values already x100)."""
    return st.column_config.NumberColumn(label, help=help_text, format=f"%.{d}f%%")


def int_col(label: str, help_text: str | None = None) -> st.column_config.NumberColumn:
    """Column config for counts."""
    return st.column_config.NumberColumn(label, help=help_text, format="localized")
