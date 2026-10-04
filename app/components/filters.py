"""Global filters in the sidebar, persisted in ``st.session_state``, with active chips."""

from __future__ import annotations

import html

import streamlit as st

from src.services.filters import (
    ALL_BANDS,
    ALL_SEGMENTS,
    COMPARE_OPTIONS,
    VINTAGE_GROUPS,
    Filters,
    segment_options,
)
from src.utils.helpers import load_params

KEYS = {
    "as_of": "f_as_of",
    "compare": "f_compare",
    "mob_band": "f_mob_band",
    "vintage_group": "f_vintage",
    "segment": "f_segment",
}
DEFAULTS = {
    "f_as_of": 0,
    "f_compare": "vs 1M earlier",
    "f_mob_band": ALL_BANDS,
    "f_vintage": "All vintages",
    "f_segment": ALL_SEGMENTS,
}


def _init() -> None:
    for k, v in DEFAULTS.items():
        st.session_state.setdefault(k, v)


def clear() -> None:
    """Reset every global filter to its default."""
    for k, v in DEFAULTS.items():
        st.session_state[k] = v


def render() -> Filters:
    """Draw the global filters in the sidebar and return the active selection."""
    _init()
    p = load_params()
    bands = [ALL_BANDS] + [b["label"] for b in p["mob_bands"]]
    segs = segment_options(
        [b["label"] for b in p["age_bands"]], ["Q1 (lowest)", "Q2", "Q3", "Q4 (highest)"]
    )
    sb = st.sidebar
    sb.markdown('<div class="ccrm-side-label">Global filters</div>', unsafe_allow_html=True)
    sb.slider(
        "As-of relative month",
        -60,
        0,
        key="f_as_of",
        help="Relative month index; 0 is the extraction month. Calendar dates are unknown.",
    )
    sb.selectbox("Comparison period", list(COMPARE_OPTIONS), key="f_compare")
    sb.selectbox(
        "MOB band", bands, key="f_mob_band", help="Months on book since the first non-X month."
    )
    sb.selectbox(
        "Vintage group", list(VINTAGE_GROUPS), key="f_vintage", help="Relative month of opening."
    )
    sb.selectbox(
        "Segment (matched clients)",
        segs,
        key="f_segment",
        help="Age or income band. Only clients with a non-conflicting application record.",
    )
    f = Filters(
        as_of=int(st.session_state["f_as_of"]),
        compare=COMPARE_OPTIONS[st.session_state["f_compare"]],
        mob_band=st.session_state["f_mob_band"],
        vintage_group=st.session_state["f_vintage"],
        segment=st.session_state["f_segment"],
    )
    sb.button("Clear filters", on_click=clear, width="stretch", disabled=not f.any_active)
    return f


def chips(f: Filters) -> None:
    """Show active-filter chips under the page title."""
    items = []
    if f.as_of != 0:
        items.append(f"As of M{f.as_of}")
    if f.compare != 1:
        items.append(f"Compare vs {f.compare}M earlier")
    if f.mob_band != ALL_BANDS:
        items.append(f"MOB {f.mob_band}")
    if f.vintage_group != "All vintages":
        items.append(f.vintage_group)
    if f.segment != ALL_SEGMENTS:
        items.append(f.segment)
    if items:
        st.markdown(
            "".join(f'<span class="ccrm-chip FILTER">{html.escape(i)}</span>' for i in items),
            unsafe_allow_html=True,
        )
