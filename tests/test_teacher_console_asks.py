"""Three things the teacher console asked for on 17 September.

Each was a read that existed with no way to reach or act on it: a session
detail whose id appeared on nothing, an acknowledged flag nothing could set,
and a preference switch no notification could be matched to.
"""

from __future__ import annotations

import pytest

from nevo.domain.accounts.vocabulary import (
    NOTIFICATION_CATEGORY_BY_TYPE,
    NotificationCategory,
    NotificationType,
    notification_category,
)
from nevo.main import app

SESSIONS = "/api/v1/students/{student_id}/sessions"
SESSION_DETAIL = "/api/v1/students/{student_id}/sessions/{session_id}"
ACKNOWLEDGE = "/api/v1/escalations/{escalation_id}/acknowledge"


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


class TestSessionsAreReachable:
    def test_a_list_exists_to_open_the_detail_from(self, spec: dict) -> None:
        assert SESSIONS in spec["paths"]
        assert "get" in spec["paths"][SESSIONS]

    def test_each_row_carries_the_id_the_detail_needs(self, spec: dict) -> None:
        row = spec["components"]["schemas"]["StudentSessionSummaryResponse"]["properties"]
        detail = spec["components"]["schemas"]["StudentSessionDetailResponse"]["properties"]

        assert "sessionId" in row
        assert "sessionId" in detail

    def test_a_row_says_enough_to_be_listed_without_opening_it(self, spec: dict) -> None:
        row = spec["components"]["schemas"]["StudentSessionSummaryResponse"]["properties"]

        assert {"lessonTitle", "occurredAt", "completionStatus", "sitting"} <= set(row)

    def test_it_pages(self, spec: dict) -> None:
        names = {p["name"] for p in spec["paths"][SESSIONS]["get"]["parameters"]}

        assert {"limit", "offset"} <= names


class TestEscalationsCanBeClosed:
    def test_an_acknowledge_write_exists(self, spec: dict) -> None:
        assert ACKNOWLEDGE in spec["paths"]
        assert "post" in spec["paths"][ACKNOWLEDGE]

    def test_it_says_who_acknowledged_and_when(self, spec: dict) -> None:
        # A teacher asking "has anyone looked at this" is better answered by a
        # name and a time than by a boolean that can say neither.
        fields = spec["components"]["schemas"]["EscalationResponse"]["properties"]

        assert {"acknowledged", "acknowledgedAt", "acknowledgedBy"} <= set(fields)


class TestMutingACategoryCanWork:
    def test_a_notification_says_which_category_it_is(self, spec: dict) -> None:
        fields = spec["components"]["schemas"]["NotificationResponse"]["properties"]

        assert "category" in fields

    @pytest.mark.parametrize("notification_type", list(NotificationType))
    def test_every_kind_of_notification_can_be_muted(
        self, notification_type: NotificationType
    ) -> None:
        # A switch that silences nothing is worse than no switch: the teacher
        # believes they have turned something off.
        assert notification_category(notification_type) is not None

    def test_every_category_maps_to_the_preference_enum(self) -> None:
        assert set(NOTIFICATION_CATEGORY_BY_TYPE.values()) <= set(NotificationCategory)

    def test_an_unknown_type_has_no_category_rather_than_a_wrong_one(self) -> None:
        # The stored column defaults to "general", which is not a category any
        # switch offers. Saying so beats picking one it does not belong to.
        assert notification_category("general") is None
        assert notification_category("something_added_later") is None
        assert notification_category(None) is None
