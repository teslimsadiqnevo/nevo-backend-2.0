from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.intelligence import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.intelligence.vocabulary import ScaffoldIntensity, ScaffoldOutcome
from nevo.intelligence.entities import (
    ScaffoldConceptState,
    ScaffoldDecision,
    ScaffoldProblemLogEntry,
)
from nevo.intelligence.scaffold_service import ScaffoldFadingService


class FakeScaffoldFadingService(ScaffoldFadingService):
    def __init__(self) -> None:
        self.recorded = []

    async def current_state(self, *, student_id, concept_id):
        return ScaffoldConceptState(
            student_id=student_id,
            concept_id=concept_id,
            current_intensity=ScaffoldIntensity.FULL_SUPPORT,
        )

    async def record_attempt(self, attempt):
        self.recorded.append(attempt)
        return ScaffoldDecision(
            state=ScaffoldConceptState(
                student_id=attempt.student_id,
                concept_id=attempt.concept_id,
                current_intensity=ScaffoldIntensity.PARTIAL_SUPPORT,
            ),
            previous_intensity=ScaffoldIntensity.FULL_SUPPORT,
            next_intensity=ScaffoldIntensity.PARTIAL_SUPPORT,
            outcome=ScaffoldOutcome.CORRECT,
            level_changed=True,
            change_reason="mastery_signals_accumulated",
            student_message="Support adjusted for the next problem.",
        )

    async def history(self, *, student_id, concept_id=None, limit=100):
        return (
            ScaffoldProblemLogEntry(
                student_id=student_id,
                concept_id=concept_id or uuid4(),
                problem_id="p1",
                scaffold_intensity=ScaffoldIntensity.FULL_SUPPORT,
                outcome=ScaffoldOutcome.CORRECT,
                response_time_ms=2_000,
                expected_response_time_ms=2_200,
                hint_count=0,
                next_scaffold_intensity=ScaffoldIntensity.PARTIAL_SUPPORT,
                level_changed=True,
                change_reason="mastery_signals_accumulated",
            ),
        )


def client_for(*, role="student", user_id=None):
    principal = AuthPrincipal(
        user_id=user_id or uuid4(),
        role=role,
        session_id=uuid4(),
    )
    service = FakeScaffoldFadingService()
    app = FastAPI()
    app.state.scaffold_fading_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.include_router(router)
    return TestClient(app), service, principal


def test_current_scaffold_state_endpoint_returns_level_for_student() -> None:
    client, _, principal = client_for()
    concept_id = uuid4()

    response = client.get(
        f"/api/intelligence/scaffolds/state/{principal.user_id}/{concept_id}"
    )

    assert response.status_code == 200
    assert response.json()["currentIntensity"] == "full_support"


def test_record_attempt_endpoint_returns_next_scaffold_level() -> None:
    client, service, principal = client_for()
    concept_id = uuid4()

    response = client.post(
        "/api/intelligence/scaffolds/attempt",
        json={
            "studentId": str(principal.user_id),
            "conceptId": str(concept_id),
            "problemId": "p3",
            "responseCorrect": True,
            "responseTimeMs": 1_900,
            "expectedResponseTimeMs": 2_200,
            "hintCount": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nextIntensity"] == "partial_support"
    assert body["changeReason"] == "mastery_signals_accumulated"
    assert service.recorded[0].concept_id == concept_id


def test_student_cannot_write_another_students_scaffold_state() -> None:
    client, _, _ = client_for()

    response = client.post(
        "/api/intelligence/scaffolds/attempt",
        json={
            "studentId": str(uuid4()),
            "conceptId": str(uuid4()),
            "problemId": "p1",
            "responseCorrect": True,
        },
    )

    assert response.status_code == 403


def test_staff_can_view_scaffold_history_for_dashboard() -> None:
    client, _, _ = client_for(role="senco_admin")

    response = client.get(f"/api/intelligence/scaffolds/history/{uuid4()}")

    assert response.status_code == 200
    assert response.json()[0]["scaffoldIntensity"] == "full_support"
