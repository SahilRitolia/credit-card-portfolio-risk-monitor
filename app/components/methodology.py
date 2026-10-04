"""Methodology text: definitions, tooltips and the About panel (all from constants)."""

from __future__ import annotations

import streamlit as st

from src.services import store
from src.utils import constants as C


def dormant_tooltip() -> str:
    """Dormant tooltip with the return share recomputed from the data."""
    share = store.dq_report().get("dormant_return_share")
    pct = f"{share * 100:.0f}%" if share is not None else "a measured share"
    return C.DEF_DORMANT_TEMPLATE.format(pct=pct)


def state_tooltips() -> dict[str, str]:
    """Tooltip per state / headline metric."""
    return {
        "30+": C.DEF_30P,
        "60+": C.DEF_60P,
        "90+": C.DEF_90P,
        "CHARGE-OFF": C.DEF_CO,
        "1-29": C.DEF_B0,
        "PAID-OFF": C.DEF_PAID,
        "DORMANT": dormant_tooltip(),
    }


def definitions(expanded: bool = False) -> None:
    """Expander with every headline definition."""
    with st.expander("Definitions and methodology", expanded=expanded):
        st.markdown(
            "\n".join(
                [
                    f"- **Open account.** {C.DEF_OPEN} Alternative denominator: all non-X accounts.",
                    f"- **1-29 DPD.** {C.DEF_B0} Headline delinquency is measured at 30+.",
                    f"- **30+ DPD.** {C.DEF_30P}",
                    f"- **60+ DPD.** {C.DEF_60P} **90+ DPD.** {C.DEF_90P} **Charge-off.** {C.DEF_CO}",
                    f"- **Paid-off.** {C.DEF_PAID}",
                    f"- **Dormant.** {dormant_tooltip()}",
                    f"- **Cure.** {C.DEF_CURE}",
                    f"- **Forward roll.** {C.DEF_FORWARD}",
                    f"- **Persistence.** {C.DEF_PERSIST}",
                    f"- **Severe roll.** {C.DEF_SEVERE}",
                    f"- **Point of no return.** {C.DEF_PNR}",
                    f"- **MOB.** {C.DEF_MOB}",
                    "- **Intervals.** 95% percentile intervals from a client-level bootstrap (whole "
                    "histories resampled). Precomputed offline; the app never resamples.",
                ]
            )
        )


def about() -> None:
    """About panel with the verbatim problem statement and the source disclaimer."""
    with st.expander("About this monitor", expanded=False):
        st.markdown(f"**{C.PROJECT_NAME}: {C.PROJECT_SUBTITLE}**")
        st.markdown(C.PROBLEM_STATEMENT)
        st.caption(C.DISCLAIMER_SOURCE)
