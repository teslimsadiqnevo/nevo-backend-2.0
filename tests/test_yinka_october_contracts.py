"""Backend contracts clarified for the student console on 8 October."""

from nevo.api.auth import UnifiedLoginRequest
from nevo.api.frontend_unblockers import MessageThreadResponse
from nevo.api.lesson_contracts import CalculationStep, TextVariant, reading_chunks
from nevo.api.product_auth import PinResetRequest
from nevo.api.response_models import LessonQuestionAttemptResponse
from nevo.db.base import Base
from nevo.domain.signal_events.catalogue import SIGNAL_CONTRACTS
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.main import app


def test_attempt_response_owns_result_and_socratic_handoff() -> None:
    fields = LessonQuestionAttemptResponse.model_fields
    assert {"result_state", "handoff_to", "guided_prompts", "advance_after_handoff"} <= set(
        fields
    )


def test_message_thread_names_the_routing_teacher() -> None:
    assert "teacher_id" in MessageThreadResponse.model_fields


def test_every_student_id_door_accepts_sixty_characters() -> None:
    value = "A" * 60
    assert PinResetRequest(schoolCode="NEVO", loginIdentifier=value).login_identifier == value
    login = UnifiedLoginRequest(method="pin", loginIdentifier=value, pin="1234")
    assert login.login_identifier == value


def test_chunked_reading_is_stable_and_is_in_online_and_offline_contracts() -> None:
    first = reading_chunks("segment-1", "One sentence. Two sentence. Three sentence.")
    assert first == reading_chunks("segment-1", "One sentence. Two sentence. Three sentence.")
    assert first[0]["id"].startswith("chunk-")
    schemas = app.openapi()["components"]["schemas"]
    assert "readingChunks" in schemas["LessonSegmentResponse"]["properties"]
    assert "readingChunks" in schemas["OfflinePackageSegment"]["properties"]
    assert SignalEventType.READING_CHUNK_VIEWED in SIGNAL_CONTRACTS


def test_lesson_text_and_calculation_contracts_carry_rendering_structure() -> None:
    text = TextVariant.model_validate(
        {
            "body": "Force changes motion.",
            "keyTerms": [{"term": "force", "definition": "A push or pull."}],
            "equationCallouts": [{"equation": "F = ma", "label": "Force"}],
        }
    )
    assert text.key_terms[0].term == "force"
    step = CalculationStep.model_validate(
        {
            "stepId": "step-1",
            "stepNumber": 1,
            "prompt": "Tap three counters.",
            "expectedInput": "selection",
            "hint": "Count one at a time.",
            "confirmationText": "Three counters.",
            "visualUpdate": "Show three counters.",
            "equationState": "3",
            "input": "tap",
            "assembles": "3",
            "tapCount": 3,
            "highlights": [{"target": "counter-row", "role": "active"}],
        }
    )
    assert step.tap_count == 3
    assert step.highlights


def test_assignment_cancellation_is_persisted() -> None:
    columns = Base.metadata.tables["lesson_assignments"].columns
    assert {"cancellation_reason", "recall_withdrawn"} <= {column.name for column in columns}
    request = app.openapi()["paths"]["/api/v1/assignments/{assignment_id}"]["delete"]
    assert "requestBody" in request
