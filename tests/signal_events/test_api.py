from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.signals import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.signal_events.vocabulary import SignalEventType
from nevo.signal_events.service import SignalIngestionService

from .fakes import MemorySignalIngestionRepository


def client_for() -> tuple[TestClient, MemorySignalIngestionRepository, AuthPrincipal]:
    repository = MemorySignalIngestionRepository()
    principal = AuthPrincipal(
        user_id=uuid4(),
        role="student",
        session_id=uuid4(),
    )
    app = FastAPI()
    app.state.signal_ingestion_service = SignalIngestionService(repository)
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), repository, principal


def test_ingests_batched_signal_events_for_authenticated_student() -> None:
    client, repository, principal = client_for()
    session_id = uuid4()
    lesson_id = uuid4()

    response = client.post(
        "/api/signals/",
        json={
            "session": {
                "sessionId": str(session_id),
                "lessonId": str(lesson_id),
                "startedAt": "2026-07-13T12:00:00Z",
                "completionStatus": "in_progress",
            },
            "events": [
                {
                    "sessionId": str(session_id),
                    "eventType": "time_on_segment",
                    "timestamp": "2026-07-13T12:00:05Z",
                    "eventData": {"segmentId": "intro", "seconds": 5},
                },
                {
                    "sessionId": str(session_id),
                    "eventType": "modality_suggestion_shown",
                    "timestamp": "2026-07-13T12:00:08Z",
                    "segmentId": "intro",
                    "suggestedModality": "visual",
                    "triggerReason": "low_engagement",
                },
            ],
        },
    )

    assert response.status_code == 202
    assert response.json() == {
        "session_id": str(session_id),
        "accepted_events": 2,
    }
    batch = repository.batches[0]
    assert batch.session.student_id == principal.user_id
    assert batch.session.lesson_id == lesson_id
    assert batch.events[0].event_type is SignalEventType.TIME_ON_SEGMENT
    assert batch.events[1].event_data == {
        "segmentId": "intro",
        "suggestedModality": "visual",
        "triggerReason": "low_engagement",
    }


def test_rejects_events_for_a_different_session() -> None:
    client, _, _ = client_for()
    session_id = uuid4()

    response = client.post(
        "/api/signals/",
        json={
            "session": {
                "sessionId": str(session_id),
                "lessonId": str(uuid4()),
                "startedAt": "2026-07-13T12:00:00Z",
            },
            "events": [
                {
                    "sessionId": str(uuid4()),
                    "eventType": "scroll",
                    "timestamp": "2026-07-13T12:00:05Z",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "session_mismatch"


def test_accepts_completion_snapshot() -> None:
    client, repository, _ = client_for()
    session_id = uuid4()

    response = client.post(
        "/api/signals/",
        json={
            "session": {
                "sessionId": str(session_id),
                "lessonId": str(uuid4()),
                "startedAt": "2026-07-13T12:00:00Z",
                "endedAt": "2026-07-13T12:14:00Z",
                "completionStatus": "completed",
                "exitPosition": "segment-8",
                "breakCount": 1,
                "proactiveAdjustmentsCount": 3,
            },
            "events": [
                {
                    "sessionId": str(session_id),
                    "eventType": "modality_switch_outcome",
                    "timestamp": datetime(2026, 7, 13, 12, 13, tzinfo=UTC).isoformat(),
                    "segmentId": "segment-8",
                    "modality": "visual",
                    "comprehensionScore": 0.8,
                    "engagementScore": 0.9,
                    "timeOnSegment": 75,
                }
            ],
        },
    )

    assert response.status_code == 202
    snapshot = repository.batches[0].session
    assert snapshot.completion_status.value == "completed"
    assert snapshot.exit_position == "segment-8"
    assert snapshot.break_count == 1
    assert snapshot.proactive_adjustments_count == 3
