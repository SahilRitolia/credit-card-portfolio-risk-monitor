"""Canonical states, headline definitions, colours and mandatory disclaimer strings.

Everything that defines a metric or a claim lives here once and is imported everywhere else.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# States
# ---------------------------------------------------------------------------
PAID_OFF = "PAID-OFF"
DORMANT = "DORMANT"
B0 = "1-29"
B1 = "30-59"
B2 = "60-89"
B3 = "90-119"
B4 = "120-149"
CHARGE_OFF = "CHARGE-OFF"

#: Display order (severity rank 0..7).
STATES: list[str] = [PAID_OFF, DORMANT, B0, B1, B2, B3, B4, CHARGE_OFF]
STATE_ORDER: dict[str, int] = {s: i for i, s in enumerate(STATES)}

OPEN_BUCKETS: list[str] = [B0, B1, B2, B3, B4]
TRANSIENT: list[str] = [DORMANT, B0, B1, B2, B3, B4]
ABSORBING: list[str] = [PAID_OFF, CHARGE_OFF]
#: Order used by every Markov matrix: transient states first, then absorbing.
MARKOV_ORDER: list[str] = TRANSIENT + ABSORBING

#: Open account = raw status 0-5.
OPEN_STATES: list[str] = [B0, B1, B2, B3, B4, CHARGE_OFF]
DPD30_STATES: list[str] = [B1, B2, B3, B4, CHARGE_OFF]
DPD60_STATES: list[str] = [B2, B3, B4, CHARGE_OFF]
DPD90_STATES: list[str] = [B3, B4, CHARGE_OFF]
DELINQUENT_OPEN: list[str] = [B1, B2, B3, B4]
CURE_STATES: list[str] = [B0, PAID_OFF]

#: Severity rank of open buckets used by roll definitions (CHARGE-OFF most severe).
BUCKET_RANK: dict[str, int] = {B0: 1, B1: 2, B2: 3, B3: 4, B4: 5, CHARGE_OFF: 6}

RAW_STATUSES: list[str] = ["0", "1", "2", "3", "4", "5", "C", "X"]

EVIDENCE_MAPPING: dict[str, str] = {
    "0": B0,
    "1": B1,
    "2": B2,
    "3": B3,
    "4": B4,
    "5": CHARGE_OFF,
    "C": PAID_OFF,
    "X": DORMANT,
}
#: Source-literal reading (C = CURRENT, X = outside the book). Sensitivity only.
LITERAL_MAPPING: dict[str, str] = {
    "0": B0,
    "1": B1,
    "2": B2,
    "3": B3,
    "4": B4,
    "5": CHARGE_OFF,
    "C": "CURRENT",
    "X": "OUTSIDE",
}
LITERAL_STATES: list[str] = ["CURRENT", B0, B1, B2, B3, B4, CHARGE_OFF]

STATE_CLASS: dict[str, str] = {
    B0: "open, transient",
    B1: "open, transient",
    B2: "open, transient",
    B3: "open, transient",
    B4: "open, transient",
    CHARGE_OFF: "absorbing",
    PAID_OFF: "absorbing exit",
    DORMANT: "transient, outside open book",
}

# ---------------------------------------------------------------------------
# Colours (single definition; app/components/formatting.py re-exports them)
# ---------------------------------------------------------------------------
STATE_COLORS: dict[str, str] = {
    PAID_OFF: "#9AA5B1",
    DORMANT: "#CBD5E1",
    B0: "#5B9A78",
    B1: "#E0B04B",
    B2: "#E08A3C",
    B3: "#CF5C4C",
    B4: "#B23A3A",
    CHARGE_OFF: "#6B1F2A",
}

# ---------------------------------------------------------------------------
# Headline definitions (tooltips, README and methodology use these verbatim)
# ---------------------------------------------------------------------------
DEF_OPEN = "Open account: status 0-5. Primary denominator for delinquency rates."
DEF_30P = "Accounts with status 1-5. Status 0 is not included."
DEF_60P = "Status 2-5."
DEF_90P = "Status 3-5."
DEF_CO = "Status 5."
DEF_B0 = "Status 0. Behaves as the performing bucket in this data."
DEF_PAID = "Status C. Absorbing exit, not a current account."
DEF_DORMANT_TEMPLATE = (
    "Status X. No balance that month; {pct} of accounts that go dormant later return."
)
DEF_CURE = (
    "Cure (from a 30+ bucket): next state is 1-29 DPD or PAID-OFF. "
    "Reported as to 1-29, to paid-off and combined."
)
DEF_FORWARD = (
    "Forward roll for bucket b: probability the next state is a more severe open bucket "
    "or CHARGE-OFF."
)
DEF_PERSIST = "Persistence: probability of staying in the same bucket next month."
DEF_SEVERE = "Severe roll: 60-89 DPD to 90+ (90-119, 120-149 or CHARGE-OFF) next month."
DEF_CO_TRANSITION = "90+ to charge-off: 90-119 or 120-149 DPD moving to CHARGE-OFF next month."
DEF_PNR = (
    "Point of no return: the first delinquency bucket where the probability of eventual "
    "charge-off exceeds the probability of eventual pay-off."
)
DEF_MOB = "Months on book: calendar months since the first non-X month (dormant months count)."

AXIS_MONTH = "Relative month (0 = extraction month; calendar date unknown)"

# ---------------------------------------------------------------------------
# Mandatory disclaimers (Section 17). Rendered by pages 03, 05 and 06 at least.
# ---------------------------------------------------------------------------
DISCLAIMER_SOURCE = (
    "Public dataset of unknown provenance; institution, country and currency unknown; "
    "month index is relative"
)
DISCLAIMER_EL = (
    "Monetary losses are illustrative and based on assumed exposure and LGD because "
    "source data does not contain balances."
)
DISCLAIMER_CENSORING = (
    "Recent vintages have incomplete performance histories. Curves are truncated at the "
    "maximum observable MOB and are not extrapolated."
)
DISCLAIMER_RUNOFF = "Closed-cohort run-off; new originations are not modelled"
LABEL_EAD = "Illustrative assumed EAD - not observed in source data."
LABEL_LGD = "Illustrative assumed LGD - not observed in source data."

MSG_INSUFFICIENT = "Insufficient observations for this view."
MSG_UNAVAILABLE = "Not available for the selected period."
MSG_NO_INTERVAL = "Not available for the selected filter."
MSG_SEGMENT_SUPPRESSED = "Insufficient observations."
MSG_NO_CLEAR_CHANGE = "No statistically clear change"
NAIVE_CI_LABEL = "naive, ignores client clustering"

PROBLEM_STATEMENT = (
    "Static delinquency rates show where a card portfolio is today. They do not show where "
    "accounts are going. Delinquency is a migration process with two absorbing exits: an "
    "account is eventually paid off or charged off. This project builds a monitoring framework "
    "on monthly account-level status histories that measures how accounts roll between "
    "delinquency buckets, how many cure, where the point of no return lies, how vintages differ "
    "at equal months-on-book, and how long accounts take to resolve. It forecasts cohort "
    "run-off with an absorbing Markov chain, validates that forecast out-of-time against naive "
    "baselines, quantifies uncertainty with client-level bootstrap resampling, and translates "
    "the results into stressed expected loss under explicitly assumed exposure and LGD, because "
    "the source data has no balances."
)

PROJECT_NAME = "Credit Card Portfolio Risk Monitor"
PROJECT_SUBTITLE = "Delinquency Migration, Cure and Charge-off Timing"
