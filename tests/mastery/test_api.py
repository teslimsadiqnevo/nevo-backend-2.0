from unittest.mock import ANY
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.dependencies import database_session
from nevo.api.mastery import router
from nevo.auth.entities import AuthPrincipal
from nevo.domain.mastery.vocabulary import FailureAttribution
from nevo.mastery.entities import (
    ConceptMasteryAggregate,
    MasteryState,
    MasteryUpdateResult,
)
from nevo.mastery.service import MasteryService


class FakeMasteryService(MasteryService):
    def __init__(self) -> None:
        self.updates = []

    async def update(self, interaction):
        self.updates.append(interaction)
        return MasteryUpdateResult(
            state=_state(
                student_id=interaction.student_id,
                concept_id=interaction.concept_id,
                attribution=FailureAttribution.READING,
            ),
            attention_transfer=0.25,
            recommended_modality_shift=True,
        )

    async def student_mastery(self, student_id):
        return (_state(student_id=student_id, concept_id=uuid4()),)

    async def class_mastery(self, class_id):
        return (
            ConceptMasteryAggregate(
                concept_id=uuid4(),
                concept_name="Fractions",
                student_count=12,
                mastery_probability_concept=0.62,
                mastery_probability_reading=0.74,
            ),
        )

    async def school_mastery(self, school_id):
        return (
            ConceptMasteryAggregate(
                concept_id=uuid4(),
                concept_name="Fractions",
                student_count=120,
                mastery_probability_concept=0.68,
                mastery_probability_reading=0.79,
            ),
        )


def _state(
    *,
    student_id,
    concept_id,
    attribution=FailureAttribution.NONE,
) -> MasteryState:
    return MasteryState(
        student_id=student_id,
        concept_id=concept_id,
        concept_name="Fractions",
        mastery_probability_concept=0.42,
        mastery_probability_reading=0.31,
        attention_weights={},
        guess_probability=0.2,
        slip_probability=0.1,
        practice_count=3,
        last_response_correct=False,
        last_failure_attribution=attribution,
        seeding_source="test",
    )


def client_for(
    *,
    role: str = "teacher",
    user_id=None,
) -> tuple[TestClient, FakeMasteryService, AuthPrincipal]:
    principal = AuthPrincipal(
        user_id=user_id or uuid4(),
        role=role,
        session_id=uuid4(),
    )
    service = FakeMasteryService()
    app = FastAPI()
    app.state.mastery_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[database_session] = lambda: object()
    app.include_router(router)
    return TestClient(app), service, principal


@pytest.fixture(autouse=True)
def allow_isolated_mastery_actor(monkeypatch):
    async def student_access(session, principal, student_id):
        del session
        if principal.role == "student" and principal.user_id != student_id:
            raise HTTPException(status_code=403)
        return object()

    async def class_access(*args, **kwargs):
        return object()

    async def school_access(*args, **kwargs):
        return type("Actor", (), {"school_id": ANY})()

    monkeypatch.setattr("nevo.api.mastery.require_student_access", student_access)
    monkeypatch.setattr("nevo.api.mastery.require_class_access", class_access)
    monkeypatch.setattr("nevo.api.mastery.require_school_actor", school_access)


def test_update_endpoint_returns_dual_track_mastery() -> None:
    client, service, _ = client_for()
    student_id = uuid4()
    concept_id = uuid4()

    response = client.post(
        "/api/mastery/update",
        json={
            "studentId": str(student_id),
            "conceptId": str(concept_id),
            "responseCorrect": False,
            "itemTextDensity": 0.9,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["recommendedModalityShift"] is True
    assert body["mastery"]["lastFailureAttribution"] == "reading"
    assert service.updates[0].student_id == student_id


def test_student_cannot_update_another_student_context() -> None:
    client, service, _ = client_for(role="student")

    response = client.post(
        "/api/mastery/update",
        json={
            "studentId": str(uuid4()),
            "conceptId": str(uuid4()),
            "responseCorrect": True,
            "itemTextDensity": 0.2,
        },
    )

    assert response.status_code == 403
    assert service.updates == []


def test_get_endpoints_return_mastery_data() -> None:
    client, _, principal = client_for(role="student")

    student_response = client.get(f"/api/mastery/student/{principal.user_id}")
    class_response = client.get(f"/api/mastery/class/{uuid4()}")
    school_response = client.get(f"/api/mastery/school/{uuid4()}")

    assert student_response.status_code == 200
    assert student_response.json()[0]["masteryProbabilityConcept"] == 0.42
    assert class_response.status_code == 200
    assert class_response.json()[0]["studentCount"] == 12
    assert class_response.json()[0]["conceptName"] == "Fractions"
    assert school_response.status_code == 200
    assert school_response.json()[0]["studentCount"] == 120
