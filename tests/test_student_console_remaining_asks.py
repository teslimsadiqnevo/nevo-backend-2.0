"""The rest of the student console's open asks. B18, B21, B24, B26, B33, B36.

Each of these was a field or a route the console drew against and the backend
never supplied, so the screen showed sample content, an empty state, or a
promise that was not true.
"""

from __future__ import annotations

import inspect

from nevo.domain.intelligence.vocabulary import ContentSegmentType
from nevo.intelligence.adaptation import _stuck_adjustment
from nevo.intelligence.entities import ContentSegment, RuntimeSignals
from nevo.main import app

SPEC = app.openapi()
SEGMENT_KIND = next(iter(ContentSegmentType))


def _segment(**kwargs: object) -> ContentSegment:
    return ContentSegment(
        id="s1",
        segment_type=SEGMENT_KIND,
        available_modalities=(),
        **kwargs,  # type: ignore[arg-type]
    )


def _stuck(errors: int, replays: int, segment: ContentSegment):
    return _stuck_adjustment(
        signals=RuntimeSignals(consecutive_errors=errors, replay_count_on_segment=replays),
        segment=segment,
        confidence=0.8,
        evidence=(),
    )


# B18 ------------------------------------------------------------------


def test_one_wrong_answer_summons_nothing() -> None:
    # Being helped after a single mistake teaches a child that getting
    # something wrong summons an adult.
    assert _stuck(1, 0, _segment(hints=("Halve it first.",))) is None


def test_two_wrong_answers_offer_the_hint_the_segment_holds() -> None:
    adjustment = _stuck(2, 0, _segment(hints=("Halve it first.",)))

    assert adjustment is not None
    assert adjustment.action == "offer_hint"
    assert adjustment.hint == "Halve it first."


def test_going_back_over_it_and_still_failing_steps_them_through() -> None:
    # They have already tried the thing a hint would suggest.
    adjustment = _stuck(2, 1, _segment(guided_questions=("What is the bottom number?",)))

    assert adjustment is not None
    assert adjustment.action == "show_socratic_panel"
    assert adjustment.guided_questions == ("What is the bottom number?",)


def test_a_segment_with_no_help_offers_none() -> None:
    # An action whose payload the client cannot render is an instruction it
    # cannot carry out. Every explanatory segment is this case today.
    assert _stuck(5, 5, _segment()) is None


# B21 ------------------------------------------------------------------


def test_the_number_accommodation_now_directs_something() -> None:
    support = SPEC["components"]["schemas"]["EngineSupportConfig"]["properties"]

    # It was inferred and reported and nothing acted on it, while staff were
    # told "Nevo works through number problems a step at a time".
    assert "numberProblemsStepByStep" in support
    assert "shorterTextBlocks" in support


# B24 ------------------------------------------------------------------


def test_one_read_at_the_start_of_a_session() -> None:
    assert "/api/session/state/{student_id}" in SPEC["paths"]
    state = SPEC["components"]["schemas"]["SessionStateResponse"]["properties"]

    # Engine config, accommodations and the consent gate from one moment, so
    # the three cannot disagree with each other.
    assert {"engineConfig", "accommodations", "consentState", "configured"} <= set(state)


def test_the_engine_config_is_typed_rather_than_a_bag() -> None:
    config = SPEC["components"]["schemas"]["EngineConfig"]["properties"]

    assert {"reading", "pacing", "support", "version"} <= set(config)
    # And the scaffold level it carries is a real rung on the ladder. It used
    # to emit "partial" and "full", which are not ScaffoldingLevel values at
    # all, so the one setting saying how much help a child starts with could
    # not be read against the ladder it belongs to.
    from nevo.domain.intelligence.vocabulary import ScaffoldingLevel
    from nevo.intelligence.baseline import build_baseline_profile

    for accuracy in (0.9, 0.4):
        _, engine = build_baseline_profile(session_id="s", features=[{"accuracy": accuracy}])
        level = engine["support"]["initialScaffoldLevel"]  # type: ignore[index]
        assert level in {item.value for item in ScaffoldingLevel}


# B26 ------------------------------------------------------------------


def test_the_check_in_reports_per_concept() -> None:
    progress = SPEC["components"]["schemas"]["LessonProgressResponse"]["properties"]

    # These three were in the contract and nothing ever set them, so the
    # "From the check-in" part of the result only ever showed sample content.
    assert {"masteredConcepts", "revisitConcepts", "resultNote"} <= set(progress)


def test_the_note_cannot_contradict_the_lists_it_came_from() -> None:
    from nevo.api.product_learning import _result_note

    assert _result_note([], []) == ""
    assert "Fractions" in _result_note([{"conceptName": "Fractions"}], [])
    both = _result_note([{"conceptName": "Fractions"}], [{"conceptName": "decimals"}])
    assert "Fractions" in both and "Decimals" in both


def test_a_concept_is_only_mastered_when_every_question_landed() -> None:
    from nevo.api.product_learning import _check_in_outcome

    source = inspect.getsource(_check_in_outcome)
    # "Mostly right" on the idea the lesson was about is not a reason to move
    # on, and the child reads a sentence rather than a score.
    assert 'tally["correct"] == tally["asked"]' in source


# B33 and B36 ----------------------------------------------------------


def test_a_spent_allowance_is_documented_not_just_returned() -> None:
    # The 429 was always raised; it was missing from the spec, so a generated
    # client could not tell it from a connection failure.
    assert "429" in SPEC["paths"]["/api/v1/ask-nevo/"]["post"]["responses"]


def test_a_crash_has_somewhere_to_go() -> None:
    assert "/api/v1/client-errors" in SPEC["paths"]
    report = SPEC["components"]["schemas"]["ClientErrorReport"]["properties"]

    # Enough to find the fault, and nothing about the child.
    assert {"message", "route", "stack", "appVersion", "incidentId"} <= set(report)
    accepted = SPEC["components"]["schemas"]["ClientErrorAccepted"]["properties"]
    assert "incidentId" in accepted


def test_there_is_no_way_to_read_crash_reports_back() -> None:
    # A store of client crashes that staff can browse becomes a store of
    # whatever those crashes happened to contain.
    crash_paths = [path for path in SPEC["paths"] if "client-error" in path]
    assert crash_paths == ["/api/v1/client-errors"]
    assert "get" not in SPEC["paths"]["/api/v1/client-errors"]
