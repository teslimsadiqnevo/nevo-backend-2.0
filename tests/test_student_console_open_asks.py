"""Contracts requested by the student console on 27 September."""

from nevo.api.frontend_unblockers import _BASELINE_ITEMS
from nevo.api.response_models import LessonQuestionAttemptResponse
from nevo.ask_nevo.service import interpret_help_state
from nevo.content_parsing.entities import ParsedLessonSegment
from nevo.content_parsing.service import _lesson_description
from nevo.db.base import Base
from nevo.domain.intelligence.vocabulary import ContentModality, LessonContentType
from nevo.main import app


def test_answer_attempts_have_a_write_and_a_read_contract() -> None:
    operations = app.openapi()["paths"]["/api/v1/lessons/{lesson_id}/attempts"]
    assert {"get", "post"} <= set(operations)
    assert {
        "lesson_id",
        "session_id",
        "question_id",
        "question",
        "answer",
        "correct",
        "attempt_number",
    } <= set(LessonQuestionAttemptResponse.model_fields)
    table = Base.metadata.tables["lesson_question_attempts"]
    assert {"question_snapshot", "answer", "correct", "submitted_at"} <= {
        column.name for column in table.columns
    }


def test_every_warm_up_dimension_has_rotating_server_owned_items() -> None:
    assert set(_BASELINE_ITEMS) == {
        "working_memory",
        "attention",
        "reading_fluency",
        "number_sense",
    }
    assert all(len(items) >= 3 for items in _BASELINE_ITEMS.values())
    spec = app.openapi()
    schema = spec["components"]["schemas"]["BaselinePromptResponse"]["properties"]
    assert {"dimension", "itemId", "question", "options"} <= set(schema)
    # The answer key must NOT be here. It was, which put the key on the device
    # and left the child's pick to be marked there - and the architecture
    # forbids the client deciding correctness. Ask B8.
    assert "answer" not in schema
    # So the pick has somewhere to go, and is marked on this side.
    assert "/api/baseline/recalibrate-prompt/{student_id}/response" in spec["paths"]
    # And whether today's warm-up is done is held against the account rather
    # than one tablet, which was offering it twice. Ask B10.
    assert "doneToday" in schema


def test_lesson_description_has_a_deterministic_fallback() -> None:
    segment = ParsedLessonSegment(
        segment_key="one",
        content_type=LessonContentType.EXPLANATORY_TEXT,
        sequence_order=1,
        title="An idea",
        body="A short explanation of the idea.",
        available_modalities=(ContentModality.TEXT,),
    )
    assert _lesson_description([segment]) == "A short explanation of the idea."
    fields = app.openapi()["components"]["schemas"]["LessonDetailResponse"]["properties"]
    assert "description" in fields


def test_ask_nevo_refusal_is_explicit_and_marker_is_not_rendered() -> None:
    can_help, reason, answer = interpret_help_state(
        "[[CANNOT_HELP]] I can't help with that here. Please ask your teacher."
    )
    assert can_help is False
    assert reason == "outside_scope"
    assert "CANNOT_HELP" not in answer
    fields = app.openapi()["components"]["schemas"]["AskResponse"]["properties"]
    assert {"canHelp", "cannotHelpReason"} <= set(fields)


def test_avatar_tone_has_a_typed_profile_home() -> None:
    assert "avatar_tone" in Base.metadata.tables["users"].columns
    fields = app.openapi()["components"]["schemas"]["CurrentUserResponse"]["properties"]
    patch = app.openapi()["components"]["schemas"]["ProfilePatch"]["properties"]
    assert "avatarTone" in fields
    assert "avatarTone" in patch
