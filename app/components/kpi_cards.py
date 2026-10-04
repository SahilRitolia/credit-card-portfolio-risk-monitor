"""KPI cards rendered as HTML (value, comparison, change, n, small-n flag, interval)."""

from __future__ import annotations

import html
import math
from typing import Any

import streamlit as st

from app.components.formatting import ci, num, pct, pp


def _dir(v: float | None, neutral: bool = False) -> str:
    if neutral or v is None or (isinstance(v, float) and math.isnan(v)) or v == 0:
        return "flat"
    return "up" if v > 0 else "down"


def card_html(
    label: str, value: str, lines: list[str], tooltip: str = "", chips: list[str] | None = None
) -> str:
    """HTML for one card."""
    tip = f'<span class="info" title="{html.escape(tooltip)}">i</span>' if tooltip else ""
    chip_html = "".join(
        f'<span class="ccrm-chip {c}">{html.escape(c)} n</span>'
        if c == "SMALL"
        else f'<span class="ccrm-chip {c}">{html.escape(c)}</span>'
        for c in (chips or [])
    )
    body = "".join(f'<div class="sub">{ln}</div>' for ln in lines)
    return (
        f'<div class="ccrm-card"><div class="lbl"><span>{html.escape(label)}</span>{tip}</div>'
        f'<div class="val">{value}</div>{body}<div style="margin-top:4px">{chip_html}</div></div>'
    )


def portfolio_kpis(cards: list[dict[str, Any]], compare_label: str, insufficient: str) -> None:
    """Render the six overview KPI cards."""
    cols = st.columns(len(cards))
    for col, c in zip(cols, cards, strict=True):
        if c["missing"]:
            col.markdown(
                card_html(c["label"], "&mdash;", [insufficient], c["tooltip"]),
                unsafe_allow_html=True,
            )
            continue
        if c["kind"] == "count":
            value = num(c["value"])
            ch = c["change"]
            lines = [
                f"{compare_label}: {num(c['compare'])}",
                f'<span class="{_dir(ch, True)}">change {num(ch) if ch < 0 else "+" + num(ch)}</span>'
                if not math.isnan(ch)
                else "comparison n/a",
            ]
        else:
            value = pct(c["value"], 2)
            lines = [
                f"{compare_label}: {pct(c['compare'], 2)}",
                f'<span class="{_dir(c["pp"], c["label"] == "1-29 DPD")}">{pp(c["pp"])} &middot; {c["change"]:+,.0f} accounts</span>'
                if not math.isnan(c["pp"])
                else "comparison n/a",
            ]
            if c["ci"]:
                lines.append(ci(*c["ci"], kind="pct", d=2))
        lines.append(f"n = {num(c['n'])}")
        col.markdown(
            card_html(c["label"], value, lines, c["tooltip"], ["SMALL"] if c["small_n"] else None),
            unsafe_allow_html=True,
        )


def metric_cards(items: list[dict[str, Any]], per_row: int = 5) -> None:
    """Generic rate cards: label, value (probability), n, events, optional interval."""
    for start in range(0, len(items), per_row):
        row = items[start : start + per_row]
        cols = st.columns(per_row)
        for col, c in zip(cols, row, strict=False):
            v = c.get("value")
            if v is None or (isinstance(v, float) and math.isnan(v)):
                col.markdown(
                    card_html(
                        c["label"],
                        "&mdash;",
                        [c.get("empty", "Insufficient observations for this view.")],
                        c.get("tooltip", ""),
                    ),
                    unsafe_allow_html=True,
                )
                continue
            lines = []
            if c.get("ci"):
                lines.append(ci(*c["ci"], kind="pct", d=c.get("d", 1)))
            elif c.get("ci_note"):
                lines.append(c["ci_note"])
            if c.get("events") is not None:
                lines.append(f"{num(c['events'])} of {num(c['n'])}")
            elif c.get("n") is not None:
                lines.append(f"n = {num(c['n'])}")
            for extra in c.get("lines", []):
                lines.append(extra)
            col.markdown(
                card_html(
                    c["label"],
                    c.get("display") or pct(v, c.get("d", 1)),
                    lines,
                    c.get("tooltip", ""),
                    c.get("chips"),
                ),
                unsafe_allow_html=True,
            )


def value_card(
    label: str, value: str, lines: list[str], tooltip: str = "", chips: list[str] | None = None
) -> None:
    """Render a single card in the current container."""
    st.markdown(card_html(label, value, lines, tooltip, chips), unsafe_allow_html=True)
