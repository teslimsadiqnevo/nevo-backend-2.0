"""How a safety hold on a /me learner's own upload is treated.

Lydia, ruling A, 24 November 2026. A school lesson's flagged content goes to
the school for review. On /me there is no school, and the learner uploaded
their own material off their own syllabus, so flagged content is released to
them with the passage named - otherwise a sixteen-year-old revising Things
Fall Apart gets nothing. Hard refusals hold for everyone, adult or under-18.

Hard is defined from what the checker already says, never a new tier:
a safeguard (a child who may be in danger), any of the serious categories
the v2 policy already names (SERIOUS_CATEGORIES: sexual exploitation,
grooming, self-harm, dangerous instructions, sexual content), or a refusal
that names no category at all, which is treated as hard because nothing
says it is not. Everything else held at the source check is flagged.

A refusal of Nevo's own generated content is neither: the learner's source
passed its check, so their own text is released and no passage of theirs is
named, because it was not theirs that was refused.
"""

from __future__ import annotations

from typing import Literal

from nevo.ai_gateway.safety import SERIOUS_CATEGORIES, SafetyBlocked

AUDIENCE_KEY = "meAudience"
INDIVIDUAL = "individual"

Treatment = Literal["hard", "flagged", "generated"]


def for_individual(source_metadata: dict) -> bool:
    return source_metadata.get(AUDIENCE_KEY) == INDIVIDUAL


def treatment(error: SafetyBlocked) -> Treatment:
    if error.phase != "lesson_source":
        return "generated"
    if error.disposition == "safeguard":
        return "hard"
    categories = set(error.categories or ())
    if not categories or categories & SERIOUS_CATEGORIES:
        return "hard"
    return "flagged"
