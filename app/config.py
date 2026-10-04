"""App-level configuration: page registry, paths and runtime checks."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent
CSS_PATH = APP_DIR / "assets" / "styles.css"

#: (file, title, url_path) in navigation order.
PAGES: list[tuple[str, str, str]] = [
    ("pages/01_portfolio_overview.py", "Executive Overview", "overview"),
    ("pages/02_roll_rates.py", "Roll Rates", "roll-rates"),
    ("pages/03_vintage_performance.py", "Vintage Performance", "vintage"),
    ("pages/04_delinquency_cure.py", "Delinquency & Cure", "cure"),
    ("pages/05_forecast_validation.py", "Forecast & Validation", "forecast"),
    ("pages/06_stress_testing.py", "Stress Testing", "stress"),
    ("pages/07_data_quality.py", "Data Quality", "data-quality"),
]

PAGES_STATE_KEY = "_ccrm_pages"


def supports_plotly_selection() -> bool:
    """True when the installed Streamlit supports ``st.plotly_chart(on_select=...)``."""
    import inspect

    return "on_select" in inspect.signature(st.plotly_chart).parameters
