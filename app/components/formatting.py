"""Design tokens, number formatting and the shared Plotly template.

State colours are defined once in ``src/utils/constants.py`` and re-exported here so every
chart uses identical colours.
"""

from __future__ import annotations

import math

import plotly.graph_objects as go
import plotly.io as pio

from src.utils.constants import STATE_COLORS, STATES

NAVY = "#0B1F3A"
CHARCOAL = "#1F2937"
MUTED = "#6B7280"
BG = "#F3F4F6"
CARD = "#FFFFFF"
BORDER = "#E5E7EB"
ACCENT = "#1F5FBF"
POSITIVE = "#3F8F6B"
WARNING = "#D99A1E"
NEGATIVE = "#B5403A"
GRID = "#EEF0F3"
FONT = "Inter, 'Segoe UI', system-ui, -apple-system, sans-serif"
SEQ_SCALE = [[0.0, "#F4F7FC"], [0.35, "#A9C1E8"], [0.7, "#3E74C9"], [1.0, "#0B1F3A"]]
SERIES = {
    "30+": "#E0B04B",
    "60+": "#E08A3C",
    "90+": "#CF5C4C",
    "CHARGE-OFF": "#6B1F2A",
    "1-29": "#5B9A78",
}
MODEL_COLORS = {
    "markov": ACCENT,
    "markov_rolling": "#6C93D6",
    "mob_conditioned": "#0B1F3A",
    "markov_observed": "#A9C1E8",
    "persistence": "#9AA5B1",
    "static_mix": "#CBD5E1",
    "oracle": "#3F8F6B",
}
STATUS_COLORS = {"PASS": POSITIVE, "WARNING": WARNING, "FAIL": NEGATIVE}

__all__ = ["STATE_COLORS", "STATES"]


def _bad(v: float | None) -> bool:
    return v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v)))


def pct(v: float | None, d: int = 1) -> str:
    """Probability as a percentage string ('n/a' when missing)."""
    return "n/a" if _bad(v) else f"{v * 100:.{d}f}%"


def pp(v: float | None, d: int = 2) -> str:
    """Percentage-point value with sign."""
    return "n/a" if _bad(v) else f"{v:+.{d}f} pp"


def num(v: float | None, d: int = 0) -> str:
    """Thousands-separated number."""
    return "n/a" if _bad(v) else f"{v:,.{d}f}"


def money(v: float | None, cur: str, d: int = 0) -> str:
    """Illustrative monetary amount with the configured symbol."""
    return "n/a" if _bad(v) else f"{cur}{v:,.{d}f}"


def ci(lo: float | None, hi: float | None, kind: str = "pct", d: int = 1, cur: str = "") -> str:
    """'95% CI a to b' in the requested unit, or empty when unavailable."""
    if _bad(lo) or _bad(hi):
        return ""
    if kind == "pct":
        return f"95% CI {lo * 100:.{d}f}% to {hi * 100:.{d}f}%"
    if kind == "money":
        return f"95% CI {cur}{lo:,.0f} to {cur}{hi:,.0f}"
    if kind == "pp":
        return f"95% CI {lo:+.{d}f} to {hi:+.{d}f} pp"
    return f"95% CI {lo:,.{d}f} to {hi:,.{d}f}"


def _template() -> go.layout.Template:
    t = go.layout.Template()
    t.layout = go.Layout(
        font={"family": FONT, "color": CHARCOAL, "size": 12},
        paper_bgcolor=CARD,
        plot_bgcolor=CARD,
        colorway=[ACCENT, "#E08A3C", "#3F8F6B", "#B23A3A", "#6C93D6", "#9AA5B1"],
        margin={"l": 56, "r": 18, "t": 64, "b": 58},
        title={
            "font": {"size": 14, "color": CHARCOAL},
            "x": 0.0,
            "xanchor": "left",
            "y": 0.97,
            "yanchor": "top",
        },
        xaxis={
            "gridcolor": GRID,
            "zeroline": False,
            "linecolor": BORDER,
            "ticks": "outside",
            "tickcolor": BORDER,
            "automargin": True,
        },
        yaxis={"gridcolor": GRID, "zeroline": False, "linecolor": BORDER, "automargin": True},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "xanchor": "right",
            "x": 1,
            "bgcolor": "rgba(0,0,0,0)",
        },
        hoverlabel={
            "bgcolor": "white",
            "bordercolor": BORDER,
            "font": {"family": FONT, "size": 12},
        },
    )
    return t


pio.templates["ccrm"] = _template()
TEMPLATE = "ccrm"
PLOTLY_CONFIG = {
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "scale": 2},
    "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"],
}
