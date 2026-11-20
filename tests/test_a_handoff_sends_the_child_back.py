"""The hand-off returns a child to the check they missed, never past it.

Lydia, 20 November: the hand-off happens *because* the child was stuck on a
step. Sending them forward means we never learn whether the conversation
worked, and the mastery estimate keeps carrying the miss.

This held the opposite value in production for weeks. The field was computed
from COMPREHENSION_GATE_ENABLED, which is off, so every hand-off told the
player to advance - while the response model's own description said "Always
false". A test, not a comment, is what keeps the two in step.
"""

from __future__ import annotations

import inspect

from nevo.api import product_learning
from nevo.api.response_models import LessonQuestionAttemptResponse


def test_the_response_model_still_promises_the_child_never_advances() -> None:
    field = LessonQuestionAttemptResponse.model_fields["advance_after_handoff"]
    assert field.default is False
    assert "Always false" in (field.description or "")


def test_the_route_hardcodes_it_and_does_not_consult_the_gate() -> None:
    source = inspect.getsource(product_learning._attempt_payload_with_outcome)
    assert 'payload["advanceAfterHandoff"] = False' in source
    # Guard against the regression itself returning: the flag that gates
    # *holding* a child at a missed check must never decide this field again.
    advance_lines = [
        line for line in source.splitlines() if "advanceAfterHandoff" in line
    ]
    assert len(advance_lines) == 1
    assert "comprehension_gate_enabled" not in advance_lines[0]
