"""Every dashboard page runs in deploy mode with default and extreme filters."""

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src.utils import constants as C

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "app" / "pages").glob("*.py"))
os.environ["CCRM_DATA_MODE"] = "deploy"


def _run(page: Path, state: dict | None = None) -> AppTest:
    at = AppTest.from_file(str(page), default_timeout=180)
    for k, v in (state or {}).items():
        at.session_state[k] = v
    return at.run()


def _text(at: AppTest) -> str:
    parts = [str(m.value) for m in at.markdown] + [str(c.value) for c in at.caption]
    parts += [str(i.value) for i in at.info] + [str(w.value) for w in at.warning]
    return "\n".join(parts)


def test_seven_pages() -> None:
    assert len(PAGES) == 7


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_page_default(page: Path) -> None:
    at = _run(page)
    assert not at.exception, at.exception
    assert len(at.markdown) >= 4


EXTREMES = [
    {"f_as_of": -60, "f_compare": "vs 12M earlier"},
    {"f_mob_band": "mature 19+", "f_vintage": "Opened M-12 to M0"},
    {"f_segment": "Age: 60+", "f_mob_band": "early 0-6"},
    {"f_segment": "Income: Q1 (lowest)", "f_as_of": -59},
]


@pytest.mark.parametrize("state", EXTREMES, ids=lambda s: "-".join(str(v) for v in s.values()))
@pytest.mark.parametrize(
    "page", [p for p in PAGES if p.stem[:2] in {"01", "02", "04"}], ids=lambda p: p.stem
)
def test_filtered_pages(page: Path, state: dict) -> None:
    at = _run(page, state)
    assert not at.exception, at.exception


def test_empty_state_messages_render() -> None:
    page = ROOT / "app" / "pages" / "01_portfolio_overview.py"
    at = _run(page, {"f_as_of": -60, "f_vintage": "Opened M-12 to M0"})
    assert not at.exception
    text = _text(at)
    assert C.MSG_INSUFFICIENT in text or C.MSG_UNAVAILABLE in text


def test_vintage_and_stress_render_disclaimers() -> None:
    at = _run(ROOT / "app" / "pages" / "03_vintage_performance.py")
    assert C.DISCLAIMER_CENSORING in _text(at)
    at = _run(ROOT / "app" / "pages" / "06_stress_testing.py")
    text = _text(at)
    assert C.DISCLAIMER_EL in text and C.LABEL_EAD in text and C.LABEL_LGD in text


def test_changing_a_filter_changes_the_output() -> None:
    page = ROOT / "app" / "pages" / "01_portfolio_overview.py"
    a = _text(_run(page))
    b = _text(_run(page, {"f_as_of": -24}))
    assert a != b


def test_stress_controls_change_el() -> None:
    page = ROOT / "app" / "pages" / "06_stress_testing.py"
    at = _run(page)
    before = _text(at)
    at.slider(key="st_m_BASE").set_value(2.0).run()
    assert not at.exception and _text(at) != before


def test_entry_point_runs() -> None:
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=180).run()
    assert not at.exception
