"""Page scaffold: CSS, custom sidebar (brand, navigation, filters, footer) and header."""

from __future__ import annotations

import html

import streamlit as st

from app.components import filters as gfilters
from app.config import CSS_PATH, PAGES, PAGES_STATE_KEY
from src.services.filters import Filters
from src.utils import constants as C


def _css() -> None:
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def _nav() -> None:
    sb = st.sidebar
    sb.markdown(
        '<div class="ccrm-brand"><div class="l1">CREDIT RISK</div><div class="l2">PORTFOLIO MONITOR</div></div>',
        unsafe_allow_html=True,
    )
    pages = st.session_state.get(PAGES_STATE_KEY)
    if pages:
        for page in pages:
            sb.page_link(page, label=page.title)
    else:
        # Page executed on its own (tests or direct run): list the sections as text.
        sb.markdown("\n".join(f"- {title}" for _, title, _ in PAGES))


def _footer() -> None:
    st.sidebar.markdown(
        '<div class="ccrm-foot">'
        "<b>Data source</b><br>Public Kaggle dataset, provenance unknown<br><br>"
        "<b>Latest observation</b><br>Relative month 0, extraction month; calendar date unknown<br><br>"
        "<b>Model</b><br>Absorbing first-order Markov chain, 8 states"
        "</div>",
        unsafe_allow_html=True,
    )


def page_setup(title: str, subtitle: str, question: str, use_filters: bool = True) -> Filters:
    """Common page scaffold. Returns the active global filters."""
    if not st.session_state.get(PAGES_STATE_KEY):
        try:
            st.set_page_config(page_title=f"{title} | {C.PROJECT_NAME}", layout="wide")
        except st.errors.StreamlitAPIException:
            st.session_state["_ccrm_config_set"] = True
    _css()
    _nav()
    f = gfilters.render() if use_filters else Filters()
    _footer()
    st.markdown(
        f'<span class="ccrm-question">{html.escape(question)}</span>', unsafe_allow_html=True
    )
    st.markdown(f'<div class="ccrm-title">{html.escape(title)}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="ccrm-subtitle">{html.escape(subtitle)}</div>', unsafe_allow_html=True)
    if use_filters:
        gfilters.chips(f)
    return f


def banner(text: str, kind: str = "") -> None:
    """Bordered note (kind: '', 'info' or 'neg')."""
    st.markdown(
        f'<div class="ccrm-banner {kind}">{html.escape(text)}</div>', unsafe_allow_html=True
    )


def section(title: str) -> None:
    """Section heading."""
    st.markdown(f"#### {title}")
