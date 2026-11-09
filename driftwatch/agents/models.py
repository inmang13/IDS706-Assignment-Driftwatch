"""Structured outputs for the LLM nodes (and their deterministic fallbacks, which return the same
types). Cause keys come from the catalog in modules/rating_curve/causes.py plus 'inconclusive'."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from driftwatch.modules.rating_curve.causes import CAUSES

CAUSE_KEYS: tuple[str, ...] = tuple(c.key for c in CAUSES) + ("inconclusive",)
CauseKey = Literal[
    "scour",
    "fill",
    "debris",
    "vegetation",
    "datum_change",
    "measurement_quality",
    "insufficient_data",
    "inconclusive",
]
REQUIRED_CAUSES = ("datum_change", "inconclusive")


class Hypothesis(BaseModel):
    cause: CauseKey
    confidence: float = Field(ge=0.0, le=1.0, description="0..1; all listed sum to about 1")
    sign_matches: bool = Field(description="cause's expected residual sign fits the observed one")
    evidence: list[str] = Field(default_factory=list, description="short facts for and against")


class Ranking(BaseModel):
    """Ranked causes, most likely first. Always lists datum_change and inconclusive."""

    hypotheses: list[Hypothesis]
    reasoning: str = Field(default="", description="two sentences at most")

    @property
    def top(self) -> Hypothesis:
        return self.hypotheses[0]


class BestGuess(BaseModel):
    cause: CauseKey
    confidence: float = Field(ge=0.0, le=1.0)


class FieldNoteRef(BaseModel):
    note: str = Field(description="the control note, verbatim")
    date: str = Field(description="YYYY-MM-DD of the visit")


class Disagreement(BaseModel):
    """Shown when the Skeptic is under 0.6 sure and a control note says something else (rule a),
    or when the change-visit note's cause has the opposite sign to the final cause (rule b):
    both sides and what to check, instead of a plain accept."""

    best_guess: BestGuess
    field_note: FieldNoteRef
    why_they_disagree: str = Field(
        description="one or two sentences: what the note implies vs what the drift sign and "
        "channel numbers show"
    )
    recommended_check: str = Field(description="one concrete thing for the next site visit")
    rule: Literal["low_confidence", "note_sign"] | None = Field(
        default=None,
        description="set by code: low_confidence = Skeptic under 0.6 with a contradicting note; "
        "note_sign = the change-visit note's cause has the opposite sign to the final cause",
    )


class SkepticVerdict(BaseModel):
    verdict: Literal["accept", "object", "disagree"]
    objection: (
        Literal["sign_mismatch", "channel_evidence", "insufficient_evidence", "other"] | None
    ) = None
    argument: str = Field(description="one or two sentences citing the numbers")
    suggested_cause: CauseKey | None = None
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0, description="your own confidence (0-1) in the top cause"
    )
    disagreement: Disagreement | None = None


CONFIDENCE_WORDS = ("confident", "likely", "uncertain", "n/a")


class Narration(BaseModel):
    """The finding, as parts plus the full text. The graph checks the parts against the facts
    (direction and score sentence verbatim) before it uses the text."""

    direction: str = Field(description="the given direction_phrase, verbatim")
    confidence_word: str = Field(
        description="confident (>= 0.8), likely or uncertain; n/a for a Trusted gauge"
    )
    cause_or_disagreement: str = Field(description="the cause sentence, or the disagreement")
    action: str = Field(description="one concrete next step")
    score_sentence: str = Field(description="the given rating sentence, verbatim")
    text: str = Field(description="<= 200 words, one paragraph, report voice")
