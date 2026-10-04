"""Entry point: ``streamlit run app/streamlit_app.py``.

Registers the seven pages with ``st.navigation`` (default page list hidden) so the custom
sidebar in ``app/components/navigation.py`` provides persistent navigation.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

from app.config import APP_DIR, PAGES, PAGES_STATE_KEY
from src.utils.constants import PROJECT_NAME

st.set_page_config(page_title=PROJECT_NAME, layout="wide", initial_sidebar_state="expanded")

pages = [
    st.Page(str(APP_DIR / path), title=title, url_path=url, default=(i == 0))
    for i, (path, title, url) in enumerate(PAGES)
]
st.session_state[PAGES_STATE_KEY] = pages
st.navigation(pages, position="hidden").run()
