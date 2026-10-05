"""Marking happens on the server. Asks B9, B14, B27.

Four of Olayinka's high asks were one problem wearing four hats: the device
was marking children's answers against an answer key it held, and the result
fed measures of the child - the baseline vector, the scaffold ladder, mastery.
A measure of a child decided on the child's own tablet is not a measure.

B14 is settled by decision rather than by code: raw touch stays on the device,
because tap coordinates and per-element dwell are a finer behavioural record
than anything else we keep and we would be storing it continuously for every
child. What the engine needs from touch is derivable, and the two cases that
were being misread as idleness now have their own event types.
"""

from __future__ import annotations

import inspect

from nevo.api.intelligence import _mark_scaffold_answer, record_scaffold_attempt
from nevo.intelligence.baseline import reduce_trials
from nevo.main import app

SPEC = app.openapi()


def test_the_baseline_can_arrive_as_trials_rather_than_a_verdict() -> None:
    assert "/api/baseline/trials" in SPEC["paths"]
    trial = SPEC["components"]["schemas"]["BaselineTrial"]["properties"]

    # What happened, not what it meant.
    assert {"dimension", "condition", "response", "responseTimeMs"} <= set(trial)
    # The item it came from, which is how the server knows the answer.
    assert "probeItemId" in trial


def test_a_trial_from_the_probe_bank_is_marked_here() -> None:
    from nevo.api.frontend_unblockers import submit_baseline_trials

    source = inspect.getsource(submit_baseline_trials)

    # Where we hold the answer, the client's own verdict is not consulted.
    assert "correct_option" in source or "ProbeItem" in source
    assert "answers.get" in source


def test_the_reduction_happens_on_this_side() -> None:
    reduced = reduce_trials(
        [
            {
                "dimension": "attention",
                "condition": "congruent",
                "correct": True,
                "responseTimeMs": 400,
            },
            {
                "dimension": "attention",
                "condition": "congruent",
                "correct": False,
                "responseTimeMs": 1200,
            },
            {
                "dimension": "attention",
                "condition": "incongruent",
                "correct": True,
                "responseTimeMs": 600,
            },
        ]
    )

    by_condition = {row["condition"]: row for row in reduced}
    # The per-condition breakdown exists because the trials do. On a
    # pre-reduced vector it could only be taken on trust.
    assert by_condition["congruent"]["attention_accuracy"] == 0.5
    assert by_condition["incongruent"]["attention_accuracy"] == 1.0
    # Median as well as mean: one slow trial from a child who looked away
    # drags a mean of twenty and says nothing true.
    assert by_condition["congruent"]["attention_median_response_ms"] == 800.0


def test_the_old_reduced_submit_still_works() -> None:
    # Not removed. The device has been sending this since before the rule, and
    # breaking it would lose baselines rather than improve them.
    assert "/api/baseline/submit" in SPEC["paths"]


def test_scaffolded_practice_takes_the_pick_not_the_verdict() -> None:
    attempt = SPEC["components"]["schemas"]["ScaffoldAttemptRequest"]

    assert {"answer", "lessonId", "segmentId"} <= set(attempt["properties"])
    # responseCorrect is no longer required, which is the point.
    assert "responseCorrect" not in attempt["required"]


def test_a_scaffold_attempt_is_marked_against_the_stored_calculation() -> None:
    source = inspect.getsource(_mark_scaffold_answer)

    assert "LessonSegment" in source
    assert "calculation_variant" in source
    # And falls back to the client only where this side holds no answer, which
    # is the same rule the lesson attempts endpoint follows.
    assert "return bool(payload.response_correct)" in source


def test_the_scaffold_route_marks_before_it_records() -> None:
    source = inspect.getsource(record_scaffold_attempt)

    assert "_mark_scaffold_answer" in source
    assert "response_correct=correct" in source


def test_raw_touch_still_stays_on_the_device() -> None:
    from nevo.api.privacy import is_private_interaction_key

    # The B14 ruling, kept mechanical: these cannot leave the device whatever
    # anybody builds next.
    for key in ("tapX", "touchPath", "gestureKind", "dwellMs", "coordinateY"):
        assert is_private_interaction_key(key), key
    # And the two cases that were being read as idleness have their own types.
    from nevo.domain.signal_events.vocabulary import SignalEventType

    assert SignalEventType.TAP_BLOCKED
    assert SignalEventType.SYSTEM_BUSY
