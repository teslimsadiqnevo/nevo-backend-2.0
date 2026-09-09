"""A parent sees their own child, and refuses to see anyone else's."""
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api.auth import authenticated_principal
from nevo.api.parents import router
from nevo.auth.entities import AuthPrincipal
from nevo.consent.entities import ParentChildView
from nevo.domain.accounts.vocabulary import UserStatus
from nevo.parents.entities import GrowthSignals
from nevo.parents.errors import ChildNotLinkedError
from nevo.parents.service import ParentInsightService

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)
PARENT_ID = uuid4()
MY_CHILD = uuid4()
SOMEONE_ELSES_CHILD = uuid4()


class FakeConsent:
    def __init__(self) -> None:
        self.asked_for: list = []

    async def children_for_parent(self, parent_id):  # type: ignore[no-untyped-def]
        self.asked_for.append(parent_id)
        if parent_id != PARENT_ID:
            return []
        return [
            ParentChildView(
                student_id=MY_CHILD,
                first_name="Amara",
                last_name="Okafor",
                status=UserStatus.ACTIVE,
                school_id=uuid4(),
                school_name="Corona Secondary School",
            )
        ]


class FakeSignals:
    def __init__(self) -> None:
        self.reads: list = []

    async def growth_signals(self, *, student_id, window_start, window_end):  # type: ignore[no-untyped-def]
        self.reads.append(student_id)
        return GrowthSignals(
            sessions=20,
            completed_sessions=18,
            exited_sessions=2,
            exit_attempts=1,
            self_adjustments=10,
            comprehension_responses=25,
            subjects_touched=3,
            concepts_practised=20,
            concepts_confident=10,
            practice_per_confident_concept=2.0,
        )


def build(role: str = "parent_guardian"):  # type: ignore[no-untyped-def]
    signals = FakeSignals()
    service = ParentInsightService(
        repository=signals,  # type: ignore[arg-type]
        consent=FakeConsent(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )
    app = FastAPI()
    app.state.parent_insight_service = service
    app.dependency_overrides[authenticated_principal] = lambda: AuthPrincipal(
        user_id=PARENT_ID, role=role, session_id=uuid4()
    )
    app.include_router(router)
    return TestClient(app), signals


def test_a_parent_can_list_their_own_children() -> None:
    client, _ = build()

    response = client.get("/api/v1/parents/me/children")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["firstName"] == "Amara"
    assert body[0]["schoolName"] == "Corona Secondary School"


def test_only_a_parent_may_use_the_parent_surface() -> None:
    for role in ("student", "teacher", "senco_admin", "other_admin"):
        client, _ = build(role=role)

        assert client.get("/api/v1/parents/me/children").status_code == 403


def test_growth_reads_the_link_table_before_it_reads_a_signal() -> None:
    """Refused on the link, not filtered afterwards."""
    client, signals = build()

    response = client.get(
        f"/api/v1/parents/me/children/{SOMEONE_ELSES_CHILD}/growth"
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "child_not_linked"
    assert signals.reads == []


def test_growth_returns_four_statements_and_the_window_it_used() -> None:
    client, _ = build()

    response = client.get(f"/api/v1/parents/me/children/{MY_CHILD}/growth")

    assert response.status_code == 200
    body = response.json()
    assert body["studentFirstName"] == "Amara"
    assert [item["dimension"] for item in body["statements"]] == [
        "staying_with_hard_problems",
        "knowing_what_she_knows",
        "connecting_ideas",
        "learning_new_things_faster",
    ]
    # The screen can say what it compared instead of claiming a term.
    assert body["periodStart"] == "2026-06-11"
    assert body["periodEnd"] == "2026-09-09"
    assert body["comparisonStart"] == "2026-03-13"
    assert body["comparisonEnd"] == "2026-06-10"
    assert body["source"] == "live_learning_data"


def test_the_growth_payload_carries_no_counts() -> None:
    client, _ = build()

    body = client.get(f"/api/v1/parents/me/children/{MY_CHILD}/growth").json()

    for item in body["statements"]:
        assert set(item) == {"dimension", "trend", "statement"}
    assert "sessions" not in body
    assert "conceptsConfident" not in body


async def test_the_service_refuses_an_unlinked_child_directly() -> None:
    service = ParentInsightService(
        repository=FakeSignals(),  # type: ignore[arg-type]
        consent=FakeConsent(),  # type: ignore[arg-type]
        now=lambda: NOW,
    )

    with pytest.raises(ChildNotLinkedError):
        await service.growth(parent_id=PARENT_ID, student_id=SOMEONE_ELSES_CHILD)
