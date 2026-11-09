"""Cause catalog for rating-curve drift: what each cause does to the residual, and what to check.

Residual sign convention (CLAUDE.md): residual = (Q_meas - Q_rated) / Q_rated.
  scour -> positive · fill/aggradation -> negative · debris/vegetation -> negative, transient ·
  datum change/gauge rebuild -> a step of either sign with no channel evidence.
Evidence fields name columns in the snapshot (field-measurements / channel-measurements). Channel
area, width and velocity are evidence only, never predictors (Q = A·V).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ExpectedSign = Literal["positive", "negative", "either", "none"]


@dataclass(frozen=True)
class Cause:
    key: str
    label: str
    expected_sign: ExpectedSign
    transient: bool
    description: str
    evidence: tuple[str, ...]


CAUSES: tuple[Cause, ...] = (
    Cause(
        key="scour",
        label="Scour",
        expected_sign="positive",
        transient=False,
        description="The flood cut the control or channel deeper, so the same stage now carries "
        "more water than the rating says.",
        evidence=(
            "control_condition notes 'Scour'",
            "channel_area at a given stage trending up",
            "residual step positive and persistent across several visits",
        ),
    ),
    Cause(
        key="fill",
        label="Fill / aggradation",
        expected_sign="negative",
        transient=False,
        description="Sediment built up on the control, raising the water surface for the same "
        "flow, so the rating overstates discharge.",
        evidence=(
            "control_condition notes 'Fill'",
            "channel_area at a given stage trending down",
            "residual step negative and persistent across several visits",
        ),
    ),
    Cause(
        key="debris",
        label="Debris",
        expected_sign="negative",
        transient=True,
        description="Woody debris or trash on the control backs water up; usually clears with "
        "the next high flow.",
        evidence=(
            "control_condition notes 'Debris'",
            "negative residuals that recover after a later high flow",
        ),
    ),
    Cause(
        key="vegetation",
        label="Vegetation",
        expected_sign="negative",
        transient=True,
        description="Plant growth on the control or banks slows the water; seasonal, strongest "
        "in late summer.",
        evidence=(
            "control_condition notes 'Vegetation'",
            "negative residuals in the growing season that fade in winter",
        ),
    ),
    Cause(
        key="datum_change",
        label="Datum change / gauge rebuild",
        expected_sign="either",
        transient=False,
        description="The gauge or its reference point was moved or rebuilt, so every stage "
        "reading is offset; the channel itself may be unchanged.",
        evidence=(
            "a sharp step at one visit with no matching channel_area change",
            "ReferencePrimary (00065) readings around the step",
            "vertical_datum / station history",
        ),
    ),
    Cause(
        key="measurement_quality",
        label="Measurement quality",
        expected_sign="either",
        transient=True,
        description="The gaugings themselves are rough (rated Poor, indirect, or at extreme "
        "flow), so scatter looks like drift.",
        evidence=(
            "measurement_rated Poor/Fair share of recent visits",
            "observing_procedure (indirect methods)",
        ),
    ),
    Cause(
        key="insufficient_data",
        label="Insufficient data",
        expected_sign="none",
        transient=False,
        description="Too few measurements since the event to tell a shift from noise.",
        evidence=("count of non-excluded measurements after the event",),
    ),
)

_BY_KEY = {c.key: c for c in CAUSES}

# control_condition prefix (lower-case) -> cause key. "Clear", "Submerged", None -> no flag.
NOTE_TO_CAUSE = {
    "scour": "scour",
    "fill": "fill",
    "debris": "debris",
    "vegetation": "vegetation",
}


def get_cause(key: str) -> Cause:
    return _BY_KEY[key]


def causes_for_sign(direction: str) -> list[Cause]:
    """Causes consistent with a residual step of this direction ('positive'/'negative')."""
    return [c for c in CAUSES if c.expected_sign in (direction, "either")]


def cause_for_note(control_condition: str | None) -> Cause | None:
    """Map a field note like 'Fill control changed' or 'Debris - Light' to a catalog cause."""
    if not control_condition:
        return None
    note = control_condition.strip().lower()
    for prefix, key in NOTE_TO_CAUSE.items():
        if note.startswith(prefix):
            return _BY_KEY[key]
    return None


def sign_agrees(cause: Cause, direction: str) -> bool:
    return cause.expected_sign in (direction, "either")
