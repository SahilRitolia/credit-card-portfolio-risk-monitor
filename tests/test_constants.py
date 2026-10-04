"""Static checks on the canonical state definitions."""

from src.utils import constants as C


def test_states_and_classes_are_consistent() -> None:
    assert len(C.STATES) == 8
    assert set(C.MARKOV_ORDER) == set(C.STATES)
    assert C.MARKOV_ORDER[-2:] == C.ABSORBING
    assert set(C.EVIDENCE_MAPPING.values()) == set(C.STATES)
    assert C.EVIDENCE_MAPPING["C"] == C.PAID_OFF
    assert C.EVIDENCE_MAPPING["X"] == C.DORMANT
    assert C.EVIDENCE_MAPPING["0"] == "1-29"
    assert C.LITERAL_MAPPING["C"] == "CURRENT"


def test_headline_sets_follow_definitions() -> None:
    assert C.DPD30_STATES == ["30-59", "60-89", "90-119", "120-149", "CHARGE-OFF"]
    assert "1-29" not in C.DPD30_STATES
    assert C.PAID_OFF not in C.OPEN_STATES and C.DORMANT not in C.OPEN_STATES
    assert set(C.DPD90_STATES) < set(C.DPD60_STATES) < set(C.DPD30_STATES) < set(C.OPEN_STATES)


def test_every_state_has_a_fixed_colour() -> None:
    assert set(C.STATE_COLORS) == set(C.STATES)
    assert len(set(C.STATE_COLORS.values())) == 8


def test_disclaimers_are_defined() -> None:
    for name in (
        "DISCLAIMER_SOURCE",
        "DISCLAIMER_EL",
        "DISCLAIMER_CENSORING",
        "DISCLAIMER_RUNOFF",
        "LABEL_EAD",
        "LABEL_LGD",
    ):
        assert getattr(C, name).strip()
