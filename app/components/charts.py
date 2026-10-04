"""Plotly figure builders. Every chart answers a named question; no decorative charts.

Missing values are drawn as gaps (never as zero); heatmaps use a single-hue sequential scale.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from app.components.formatting import (
    ACCENT,
    BORDER,
    MODEL_COLORS,
    MUTED,
    NEGATIVE,
    POSITIVE,
    SEQ_SCALE,
    SERIES,
    STATE_COLORS,
    TEMPLATE,
)
from src.utils.constants import AXIS_MONTH


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def trend_with_ci(df: pd.DataFrame, title: str, y_title: str, height: int = 330) -> go.Figure:
    """Lines by METRIC over MONTHS_BALANCE with optional lo/hi bands."""
    fig = go.Figure()
    for met, g in df.groupby("METRIC", sort=False):
        g = g.sort_values("MONTHS_BALANCE")
        col = SERIES.get(str(met), ACCENT)
        if "lo" in g and g.lo.notna().any():
            fig.add_trace(
                go.Scatter(
                    x=g.MONTHS_BALANCE,
                    y=g.hi * 100,
                    mode="lines",
                    line={"width": 0},
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=g.MONTHS_BALANCE,
                    y=g.lo * 100,
                    mode="lines",
                    line={"width": 0},
                    fill="tonexty",
                    fillcolor=_hex_rgba(col, 0.15),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        custom = np.stack([g.num.fillna(-1), g.den.fillna(-1)], axis=-1) if "num" in g else None
        fig.add_trace(
            go.Scatter(
                x=g.MONTHS_BALANCE,
                y=g.rate * 100,
                mode="lines",
                name=str(met),
                line={"color": col, "width": 2},
                customdata=custom,
                hovertemplate=f"{met}: %{{y:.2f}}%<br>month %{{x}}<br>n = %{{customdata[0]:,.0f}} of %{{customdata[1]:,.0f}} open<extra></extra>"
                if custom is not None
                else None,
            )
        )
    fig.update_layout(
        template=TEMPLATE, title=title, height=height, xaxis_title=AXIS_MONTH, yaxis_title=y_title
    )
    return fig


def state_bars(df: pd.DataFrame, title: str, height: int = 330) -> go.Figure:
    """Horizontal bars of account counts by state (fixed state colours)."""
    d = df.copy()
    total = d.n.sum()
    fig = go.Figure(
        go.Bar(
            x=d.n,
            y=d.STATE,
            orientation="h",
            marker_color=[STATE_COLORS.get(s, MUTED) for s in d.STATE],
            text=[f"{v:,.0f}" if np.isfinite(v) else "suppressed" for v in d.n],
            textposition="outside",
            customdata=(d.n / total * 100) if total else None,
            hovertemplate="%{y}: %{x:,.0f} accounts (%{customdata:.1f}% of opened book)<extra></extra>",
        )
    )
    mx = float(np.nanmax(d.n)) if len(d) and np.isfinite(d.n).any() else 1.0
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        yaxis={"autorange": "reversed"},
        xaxis={"title": "Accounts", "range": [0, mx * 1.18]},
        showlegend=False,
    )
    return fig


def stacked_by_band(df: pd.DataFrame, title: str, height: int = 330) -> go.Figure:
    """Open stock by MOB band stacked by state."""
    fig = go.Figure()
    for s in ["1-29", "30-59", "60-89", "90-119", "120-149", "CHARGE-OFF"]:
        g = df[s == df.STATE]
        fig.add_trace(
            go.Bar(
                x=g.MOB_BAND,
                y=g.n,
                name=s,
                marker_color=STATE_COLORS[s],
                hovertemplate=f"{s}<br>%{{x}}: %{{y:,.0f}}<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        barmode="stack",
        title=title,
        height=height,
        yaxis_title="Open accounts",
        xaxis_title="MOB band (months on book)",
    )
    return fig


def waterfall(df: pd.DataFrame, title: str, height: int = 330) -> go.Figure:
    """Open-account bridge from the prior month to the as-of month."""
    measure = ["absolute"] + ["relative"] * (len(df) - 2) + ["total"]
    fig = go.Figure(
        go.Waterfall(
            x=df.step,
            y=df.value,
            measure=measure,
            text=[
                f"{v:+,.0f}" if 0 < i < len(df) - 1 else f"{v:,.0f}" for i, v in enumerate(df.value)
            ],
            textposition="outside",
            connector={"line": {"color": BORDER}},
            increasing={"marker": {"color": POSITIVE}},
            decreasing={"marker": {"color": NEGATIVE}},
            totals={"marker": {"color": ACCENT}},
        )
    )
    fig.update_layout(
        template=TEMPLATE, title=title, height=height, showlegend=False, yaxis_title="Open accounts"
    )
    return fig


def bar_ci(
    df: pd.DataFrame,
    x: str,
    y: str,
    lo: str,
    hi: str,
    title: str,
    y_title: str,
    color: str = ACCENT,
    height: int = 330,
    pct_scale: bool = True,
) -> go.Figure:
    """Bars with asymmetric 95% interval whiskers."""
    k = 100 if pct_scale else 1
    ok = df[lo].notna() & df[hi].notna()
    fig = go.Figure(
        go.Bar(
            x=df[x],
            y=df[y] * k,
            marker_color=color,
            error_y={
                "type": "data",
                "symmetric": False,
                "array": np.where(ok, (df[hi] - df[y]) * k, 0),
                "arrayminus": np.where(ok, (df[y] - df[lo]) * k, 0),
                "color": "#374151",
                "thickness": 1.2,
            },
            customdata=np.stack([df[lo] * k, df[hi] * k], axis=-1),
            hovertemplate="%{x}<br>%{y:.2f}<br>95% CI %{customdata[0]:.2f} to %{customdata[1]:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        template=TEMPLATE, title=title, height=height, yaxis_title=y_title, showlegend=False
    )
    return fig


def matrix_heatmap(
    t: pd.DataFrame,
    origins: list[str],
    dests: list[str],
    show_counts: bool,
    title: str,
    height: int = 430,
) -> go.Figure:
    """Roll-rate heatmap (percent); hover shows n and interval; clickable cell markers."""
    piv = t.pivot_table(
        index="FROM_STATE", columns="TO_STATE", values="p", aggfunc="first"
    ).reindex(index=origins, columns=dests)
    n = t.pivot_table(index="FROM_STATE", columns="TO_STATE", values="n", aggfunc="first").reindex(
        index=origins, columns=dests
    )
    rown = t.groupby("FROM_STATE").row_n.first().reindex(origins)
    lo = t.pivot_table(
        index="FROM_STATE", columns="TO_STATE", values="lo", aggfunc="first"
    ).reindex(index=origins, columns=dests)
    hi = t.pivot_table(
        index="FROM_STATE", columns="TO_STATE", values="hi", aggfunc="first"
    ).reindex(index=origins, columns=dests)
    z = piv.to_numpy() * 100
    text = []
    for i in range(len(origins)):
        row = []
        for j in range(len(dests)):
            v, c = z[i, j], n.to_numpy()[i, j]
            if np.isnan(v):
                row.append("")
                continue
            label = "0" if v == 0 else ("<0.1%" if v < 0.1 else f"{v:.1f}%")
            if show_counts and np.isfinite(c):
                label += f"<br><span style='font-size:10px'>{c:,.0f}</span>"
            row.append(label)
        text.append(row)
    lo_a, hi_a = lo.to_numpy() * 100, hi.to_numpy() * 100
    cd = np.dstack(
        [n.to_numpy(), np.repeat(rown.to_numpy()[:, None], len(dests), axis=1), lo_a, hi_a]
    )
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=dests,
            y=origins,
            text=text,
            texttemplate="%{text}",
            colorscale=SEQ_SCALE,
            zmin=0,
            zmax=100,
            customdata=cd,
            colorbar={"title": "%", "thickness": 10},
            hovertemplate="From %{y} to %{x}: %{z:.2f}%<br>n = %{customdata[0]:,.0f} of %{customdata[1]:,.0f}"
            "<br>95% CI %{customdata[2]:.2f}% to %{customdata[3]:.2f}%<extra></extra>",
            xgap=2,
            ygap=2,
        )
    )
    xs, ys = np.meshgrid(np.arange(len(dests)), np.arange(len(origins)))
    fig.add_trace(
        go.Scatter(
            x=[dests[i] for i in xs.ravel()],
            y=[origins[j] for j in ys.ravel()],
            mode="markers",
            marker={"size": 34, "color": "rgba(0,0,0,0)", "symbol": "square"},
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        xaxis_title="Next month state",
        yaxis_title="Current state",
        yaxis={"autorange": "reversed"},
        clickmode="event+select",
    )
    return fig


def line_rate(
    df: pd.DataFrame,
    x: str,
    y: str,
    title: str,
    y_title: str,
    x_title: str,
    color: str = ACCENT,
    height: int = 300,
    n_col: str | None = None,
) -> go.Figure:
    """Single rate line with n in hover."""
    cd = df[n_col] if n_col else None
    fig = go.Figure(
        go.Scatter(
            x=df[x],
            y=df[y] * 100,
            mode="lines+markers",
            line={"color": color, "width": 2},
            marker={"size": 4},
            customdata=cd,
            hovertemplate="%{x}: %{y:.2f}%"
            + ("<br>n = %{customdata:,.0f}" if n_col else "")
            + "<extra></extra>",
        )
    )
    fig.update_layout(
        template=TEMPLATE, title=title, height=height, xaxis_title=x_title, yaxis_title=y_title
    )
    return fig


def vintage_curves(df: pd.DataFrame, title: str, height: int = 420) -> go.Figure:
    """One curve per vintage quarter, stopping at the last observable MOB."""
    fig = go.Figure()
    labels = df.drop_duplicates("VINTAGE_QTR").sort_values("VINTAGE_QTR")
    n = len(labels)
    for i, (q, lab) in enumerate(zip(labels.VINTAGE_QTR, labels.VINTAGE_LABEL, strict=True)):
        g = df[q == df.VINTAGE_QTR].sort_values("MOB")
        t = i / max(n - 1, 1)
        lo_c, hi_c = (169, 193, 232), (11, 31, 58)
        color = "rgb({},{},{})".format(
            *(int(a + (b - a) * t) for a, b in zip(lo_c, hi_c, strict=True))
        )
        fig.add_trace(
            go.Scatter(
                x=g.MOB,
                y=g.rate * 100,
                mode="lines",
                name=lab,
                line={"width": 1.8, "color": color},
                customdata=np.stack([g.events, g.n_accounts], axis=-1),
                hovertemplate=f"{lab}<br>MOB %{{x}}: %{{y:.2f}}%<br>%{{customdata[0]:,.0f}} of %{{customdata[1]:,.0f}} accounts<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        xaxis_title="Months on book",
        yaxis_title="Cumulative share of vintage (%)",
        legend={
            "orientation": "v",
            "x": 1.02,
            "xanchor": "left",
            "y": 1,
            "yanchor": "top",
            "font": {"size": 10},
        },
        margin={"r": 130},
    )
    return fig


def vintage_heatmap(piv: pd.DataFrame, title: str, height: int = 520) -> go.Figure:
    """Vintage x MOB heatmap; unobservable cells left blank."""
    z = piv.to_numpy() * 100
    fig = go.Figure(
        go.Heatmap(
            z=z,
            x=list(piv.columns),
            y=list(piv.index),
            colorscale=SEQ_SCALE,
            colorbar={"title": "%", "thickness": 10},
            hovertemplate="%{y}, MOB %{x}: %{z:.2f}%<extra></extra>",
            xgap=1,
            ygap=1,
        )
    )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        xaxis_title="Months on book",
        yaxis_title="Vintage (open quarter)",
        yaxis={"autorange": "reversed"},
    )
    return fig


def outcome_stack(df: pd.DataFrame, title: str, height: int = 340) -> go.Figure:
    """Stacked shares of raw outcomes by episode group."""
    colors = {
        "CURED": "#5B9A78",
        "CHARGED-OFF": "#6B1F2A",
        "STILL 30+": "#E0B04B",
        "CENSORED": "#CBD5E1",
    }
    fig = go.Figure()
    for o in ["CURED", "STILL 30+", "CHARGED-OFF", "CENSORED"]:
        g = df[o == df.OUTCOME]
        fig.add_trace(
            go.Bar(
                y=g.GRP,
                x=g.share * 100,
                name=o,
                orientation="h",
                marker_color=colors[o],
                customdata=np.stack([g.n, g.episodes], axis=-1),
                hovertemplate=f"{o}: %{{x:.1f}}%<br>%{{customdata[0]:,.0f}} of %{{customdata[1]:,.0f}} episodes<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        barmode="stack",
        title=title,
        height=height,
        xaxis_title="% of episodes",
        yaxis={"autorange": "reversed"},
    )
    return fig


def cif_curves(df: pd.DataFrame, group: str, title: str, height: int = 340) -> go.Figure:
    """Cumulative incidence of cure and charge-off with interval bands for one group."""
    g = df[group == df.GRP].sort_values("K")
    fig = go.Figure()
    for key, name, col in (
        ("cif_cure", "Cured", "#5B9A78"),
        ("cif_co", "Charged-off", "#6B1F2A"),
        ("still_30p", "Still 30+", "#E0B04B"),
    ):
        fig.add_trace(
            go.Scatter(
                x=g.K,
                y=g[key] * 100,
                mode="lines+markers",
                name=name,
                line={"color": col, "width": 2},
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": (g[f"{key}_hi"] - g[key]) * 100,
                    "arrayminus": (g[key] - g[f"{key}_lo"]) * 100,
                    "thickness": 1,
                },
                hovertemplate=f"{name} within %{{x}}M: %{{y:.2f}}%<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        xaxis_title="Months after entering 30+",
        yaxis_title="Cumulative incidence (%)",
        xaxis={"tickmode": "array", "tickvals": list(g.K)},
    )
    return fig


def model_errors(
    df: pd.DataFrame, labels: dict[str, str], title: str, y_title: str, height: int = 360
) -> go.Figure:
    """Error by origin for each model (lines)."""
    fig = go.Figure()
    for model, g in df.groupby("model", sort=False):
        g = g.sort_values("origin")
        dash = "dot" if model in ("persistence", "static_mix", "oracle") else "solid"
        fig.add_trace(
            go.Scatter(
                x=g.origin,
                y=g.value,
                mode="lines+markers",
                name=labels.get(model, model),
                line={"color": MODEL_COLORS.get(model, MUTED), "width": 2, "dash": dash},
                hovertemplate=labels.get(model, model) + "<br>origin %{x}: %{y:.3f}<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        xaxis_title="Forecast origin (relative month)",
        yaxis_title=y_title,
    )
    return fig


def forecast_vs_actual(df: pd.DataFrame, title: str, height: int = 340) -> go.Figure:
    """Grouped bars of forecast and actual state shares."""
    fig = go.Figure()
    fig.add_trace(go.Bar(x=df.STATE, y=df.forecast * 100, name="Forecast", marker_color=ACCENT))
    fig.add_trace(go.Bar(x=df.STATE, y=df.actual * 100, name="Actual", marker_color="#9AA5B1"))
    fig.update_layout(
        template=TEMPLATE, barmode="group", title=title, height=height, yaxis_title="% of cohort"
    )
    return fig


def runoff_stack(df: pd.DataFrame, title: str, height: int = 340) -> go.Figure:
    """Projected cohort composition by horizon (stacked shares)."""
    fig = go.Figure()
    for s in ["PAID-OFF", "DORMANT", "1-29", "30-59", "60-89", "90-119", "120-149", "CHARGE-OFF"]:
        g = df[s == df.STATE]
        fig.add_trace(
            go.Bar(
                x=[f"{h}M" for h in g.horizon],
                y=g.share * 100,
                name=s,
                marker_color=STATE_COLORS[s],
                customdata=g["count"],
                hovertemplate=f"{s}: %{{y:.2f}}% (%{{customdata:,.0f}} accounts)<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        barmode="stack",
        title=title,
        height=height,
        yaxis_title="% of cohort",
        xaxis_title="Months ahead",
    )
    return fig


def calibration_chart(df: pd.DataFrame, title: str, height: int = 340) -> go.Figure:
    """Predicted vs actual charge-off counts with predictive intervals."""
    d = df.sort_values(["horizon", "origin"])
    x = [f"{o} / {h}M" for o, h in zip(d.origin, d.horizon, strict=True)]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=x,
            y=d.predicted_co,
            mode="markers",
            name="Predicted (95% predictive interval)",
            marker={"color": ACCENT, "size": 7},
            error_y={
                "type": "data",
                "symmetric": False,
                "array": d.pred_hi - d.predicted_co,
                "arrayminus": d.predicted_co - d.pred_lo,
                "color": ACCENT,
                "thickness": 1,
            },
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x,
            y=d.actual_co,
            mode="markers",
            name="Actual",
            marker={"color": NEGATIVE, "size": 8, "symbol": "diamond"},
        )
    )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        yaxis_title="Charge-offs (count)",
        xaxis_title="Origin / horizon",
        xaxis={"tickangle": -45, "tickfont": {"size": 9}},
    )
    return fig


def el_contribution(df: pd.DataFrame, cur: str, title: str, height: int = 340) -> go.Figure:
    """EL contribution by origin state as a waterfall to the total."""
    d = df[df.contribution > 0]
    measure = ["relative"] * len(d) + ["total"]
    x = list(d.STATE) + ["Total"]
    y = list(d.contribution) + [float(d.contribution.sum())]
    fig = go.Figure(
        go.Waterfall(
            x=x,
            y=y,
            measure=measure,
            text=[f"{cur}{v:,.0f}" for v in y],
            textposition="outside",
            connector={"line": {"color": BORDER}},
            increasing={"marker": {"color": NEGATIVE}},
            totals={"marker": {"color": "#6B1F2A"}},
        )
    )
    fig.update_layout(
        template=TEMPLATE,
        title=title,
        height=height,
        showlegend=False,
        yaxis_title=f"Illustrative EL ({cur})",
    )
    return fig


def scenario_bars(df: pd.DataFrame, cur: str, title: str, height: int = 340) -> go.Figure:
    """Preset EL with intervals by horizon."""
    fig = go.Figure()
    for h, col in ((6, "#6C93D6"), (12, "#0B1F3A")):
        g = df[df["Horizon (months)"] == h]
        fig.add_trace(
            go.Bar(
                x=g.Scenario,
                y=g.EL,
                name=f"{h}M",
                marker_color=col,
                error_y={
                    "type": "data",
                    "symmetric": False,
                    "array": g["EL 95% hi"] - g.EL,
                    "arrayminus": g.EL - g["EL 95% lo"],
                    "thickness": 1,
                },
                hovertemplate=f"%{{x}} {h}M: {cur}%{{y:,.0f}}<extra></extra>",
            )
        )
    fig.update_layout(
        template=TEMPLATE,
        barmode="group",
        title=title,
        height=height,
        yaxis_title=f"Illustrative EL ({cur})",
    )
    return fig
