from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.dependencies import database_session
from nevo.api.scheduler import router
from nevo.auth.entities import AuthPrincipal
from nevo.scheduler.entities import ConceptSchedule, ReviewResult
from nevo.scheduler.service import FsrsSchedulerService


class FakeSchedulerService(FsrsSchedulerService):
    def __init__(self) -> None:
        self.recorded = []

    async def due_reviews(self, *, student_id, now=None):
        return (
            ConceptSchedule(
                student_id=student_id,
                concept_id=uuid4(),
                stability=10,
                difficulty=4.5,
                retrievability=0.82,
                last_review=datetime(2026, 8, 20, tzinfo=UTC),
                review_count=1,
                next_review_due=datetime(2026, 8, 22, tzinfo=UTC),
            ),
        )

    async def record_review(
        self,
        *,
        student_id,
        concept_id,
        recall_successful,
        reviewed_at=None,
    ):
        self.recorded.append((student_id, concept_id, recall_successful, reviewed_at))
        return ReviewResult(
            recall_successful=recall_successful,
            schedule=ConceptSchedule(
                student_id=student_id,
                concept_id=concept_id,
                stability=10,
                difficulty=4.5,
                retrievability=1,
                last_review=reviewed_at or datetime(2026, 8, 22, tzinfo=UTC),
                review_count=1,
                next_review_due=datetime(2026, 8, 24, tzinfo=UTC),
            ),
        )

    async def refresh_all_due_dates(self, *, now=None):
        return ()


def client_for(*, role="student", user_id=None):
    principal = AuthPrincipal(
        user_id=user_id or uuid4(),
        role=role,
        session_id=uuid4(),
    )
    service = FakeSchedulerService()
    app = FastAPI()
    app.state.scheduler_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[database_session] = lambda: object()
    app.include_router(router)
    return TestClient(app), service, principal


@pytest.fixture(autouse=True)
def allow_isolated_scheduler_actor(monkeypatch):
    async def student_access(session, principal, student_id):
        del session
        if principal.role == "student" and principal.user_id != student_id:
            raise HTTPException(status_code=403)
        return object()

    async def school_access(*args, **kwargs):
        return object()

    monkeypatch.setattr("nevo.api.scheduler.require_student_access", student_access)
    monkeypatch.setattr("nevo.api.scheduler.require_school_actor", school_access)


def test_due_reviews_endpoint_returns_concepts_due_for_student() -> None:
    client, _, principal = client_for()

    response = client.get(f"/api/scheduler/due-reviews/{principal.user_id}")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["studentId"] == str(principal.user_id)
    assert body[0]["retrievability"] == 0.82


def test_student_cannot_view_another_students_due_reviews() -> None:
    client, _, _ = client_for()

    response = client.get(f"/api/scheduler/due-reviews/{uuid4()}")

    assert response.status_code == 403


def test_record_review_endpoint_updates_schedule() -> None:
    client, service, principal = client_for()
    concept_id = uuid4()

    response = client.post(
        "/api/scheduler/record-review",
        json={
            "studentId": str(principal.user_id),
            "conceptId": str(concept_id),
            "recallSuccessful": True,
            "reviewedAt": "2026-08-22T10:00:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["recallSuccessful"] is True
    assert service.recorded[0][1] == concept_id


def test_staff_can_trigger_daily_refresh_endpoint() -> None:
    client, _, _ = client_for(role="teacher")

    response = client.post("/api/scheduler/refresh-due-dates")

    assert response.status_code == 200
    assert response.json()["refreshedCount"] == 0
