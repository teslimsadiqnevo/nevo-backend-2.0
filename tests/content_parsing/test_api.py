from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import nevo.api.content as content_api
from nevo.api.auth import authenticated_principal
from nevo.api.content import router
from nevo.api.dependencies import database_session
from nevo.auth.entities import AuthPrincipal
from nevo.content_parsing.entities import ParseRunState
from nevo.content_parsing.service import ContentParsingService
from nevo.domain.intelligence.vocabulary import ContentParseStatus

SCHOOL_ID = uuid4()


class StubActor:
    school_id = SCHOOL_ID


@pytest.fixture(autouse=True)
def _school_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    async def actor(session, principal, roles):  # type: ignore[no-untyped-def]
        del session, principal, roles
        return StubActor()

    monkeypatch.setattr(content_api, "require_school_actor", actor)


class FakeContentParsingService(ContentParsingService):
    def __init__(self) -> None:
        self.requests: list = []
        self.lesson_id = uuid4()
        self.parse_run_id = uuid4()
        self.state = ParseRunState(
            parse_run_id=self.parse_run_id,
            lesson_id=self.lesson_id,
            school_id=SCHOOL_ID,
            status=ContentParseStatus.PROCESSING,
            requested_by_user_id=uuid4(),
            started_at=datetime(2026, 9, 9, 12, 0, tzinfo=UTC),
            completed_at=None,
            failure_reason=None,
            review_notes=(),
            segment_count=3,
            fallback_segment_count=0,
        )

    async def start(self, *, request, requested_by_user_id, existing_lesson_id=None):
        self.requests.append((request, requested_by_user_id))
        return self.lesson_id, self.parse_run_id

    async def run_state(self, parse_run_id):
        return self.state if parse_run_id == self.parse_run_id else None


def client_for() -> tuple[TestClient, FakeContentParsingService, AuthPrincipal]:
    principal = AuthPrincipal(
        user_id=uuid4(),
        role="teacher",
        session_id=uuid4(),
    )
    service = FakeContentParsingService()
    app = FastAPI()
    app.state.content_parsing_service = service
    app.dependency_overrides[authenticated_principal] = lambda: principal
    app.dependency_overrides[database_session] = lambda: None
    app.include_router(router)
    return TestClient(app), service, principal


def test_parse_is_accepted_and_hands_back_something_to_poll() -> None:
    """It used to answer synchronously after minutes of image generation, so
    every proxy in front of it hung up first."""
    client, service, principal = client_for()

    response = client.post(
        "/api/content/parse",
        json={
            "title": "Photosynthesis",
            "sourceType": "text",
            "sourceText": "Plants use sunlight.",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "processing"
    assert payload["parseRunId"] == str(service.parse_run_id)
    assert payload["lessonId"] == str(service.lesson_id)
    assert payload["pollUrl"] == f"/api/content/parse-runs/{service.parse_run_id}"
    assert service.requests[0][0].title == "Photosynthesis"
    assert service.requests[0][1] == principal.user_id


def test_the_run_id_can_actually_be_used() -> None:
    """It was returned by the parse endpoints and accepted by nothing."""
    client, service, _ = client_for()

    response = client.get(f"/api/content/parse-runs/{service.parse_run_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "processing"
    assert body["finished"] is False
    assert body["lessonId"] == str(service.lesson_id)


def test_a_finished_run_says_so_on_one_field() -> None:
    client, service, _ = client_for()
    service.state = replace(
        service.state,
        status=ContentParseStatus.COMPLETED_WITH_REVIEW,
        completed_at=datetime(2026, 9, 9, 12, 4, tzinfo=UTC),
    )

    body = client.get(f"/api/content/parse-runs/{service.parse_run_id}").json()

    assert body["finished"] is True
    assert body["completedAt"] is not None


def test_a_failed_run_says_why() -> None:
    client, service, _ = client_for()
    service.state = replace(
        service.state,
        status=ContentParseStatus.FAILED,
        completed_at=datetime(2026, 9, 9, 12, 4, tzinfo=UTC),
        failure_reason="VisualGenerationError: image provider failed",
    )

    body = client.get(f"/api/content/parse-runs/{service.parse_run_id}").json()

    assert body["finished"] is True
    assert body["failureReason"].startswith("VisualGenerationError")


def test_an_unknown_run_is_not_found() -> None:
    client, _, _ = client_for()

    assert client.get(f"/api/content/parse-runs/{uuid4()}").status_code == 404


def test_a_run_that_the_ai_contributed_nothing_to_says_so() -> None:
    """Every lesson in the library was once entirely fallback text while the
    run reported completed_with_review."""
    client, service, _ = client_for()
    service.state = replace(
        service.state,
        status=ContentParseStatus.COMPLETED_WITH_REVIEW,
        segment_count=3,
        fallback_segment_count=3,
    )

    body = client.get(f"/api/content/parse-runs/{service.parse_run_id}").json()

    assert body["segmentCount"] == body["fallbackSegmentCount"] == 3
