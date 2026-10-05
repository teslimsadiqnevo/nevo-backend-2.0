"""The round-two asks that turned out to be fixes. B44, B57, B60, B62.

Each of these started as a question and the answer was "it does not do that
yet", which makes the answer a change rather than a sentence.
"""

from __future__ import annotations

import inspect
from datetime import timedelta

from nevo.main import app

SPEC = app.openapi()


def test_b44_the_signal_stream_refuses_a_withdrawn_child() -> None:
    from nevo.api.signals import _refuse_a_withdrawn_child, ingest_signal_batch

    # The gate was on starting a lesson, recording progress, taking one
    # offline and asking Nevo - and not on the stream. So a client that
    # missed a withdrawal went on reporting a child nobody may process.
    assert "_refuse_a_withdrawn_child" in inspect.getsource(ingest_signal_batch)
    gate = inspect.getsource(_refuse_a_withdrawn_child)
    assert "require_student_consent" in gate


def test_b44_the_gate_does_not_turn_a_client_error_into_a_server_fault() -> None:
    from nevo.api.signals import _refuse_a_withdrawn_child, ingest_signal_batch

    # Resolved inside the handler, not injected. A route dependency resolves
    # before the handler, so an unreachable consent service answered 503 to
    # requests this route should have refused with 403 or 422 on its own
    # terms. Second time a route-level gate has done that.
    assert "StudentLearningConsent" not in inspect.getsource(ingest_signal_batch)
    # And an unconfigured service is not a withdrawal: refusing every child
    # because one service is down would lose a lesson's evidence to protect
    # nobody.
    assert "if service is None:" in inspect.getsource(_refuse_a_withdrawn_child)


def test_b57_a_session_cannot_renew_forever() -> None:
    from nevo.auth.policies import (
        ROLE_ABSOLUTE_LIFETIMES,
        ROLE_IDLE_TIMEOUTS,
        absolute_lifetime_for_role,
    )

    # The idle timeout slides on every authenticated request, which is what
    # keeps a child from being thrown out mid-lesson - and means a tab left
    # open and polling renewed indefinitely.
    assert set(ROLE_ABSOLUTE_LIFETIMES) == set(ROLE_IDLE_TIMEOUTS)
    for role, idle in ROLE_IDLE_TIMEOUTS.items():
        assert absolute_lifetime_for_role(role) > idle, role
    # A child's sign-in cannot carry into the next day on a shared tablet.
    assert ROLE_ABSOLUTE_LIFETIMES["student"] <= timedelta(hours=12)
    # An unknown role is capped, not uncapped.
    assert absolute_lifetime_for_role("nobody") > timedelta(0)


def test_b57_the_cap_is_counted_from_sign_in() -> None:
    from nevo.auth.service import AuthService

    source = inspect.getsource(AuthService.authenticate)

    # From created_at, not from the last request - otherwise it is just a
    # second idle timeout.
    assert "session.created_at" in source
    assert "absolute_lifetime_for_role" in source


def test_b60_the_offline_package_has_a_published_schema() -> None:
    schemas = SPEC["components"]["schemas"]

    assert "OfflinePackage" in schemas
    assert "/api/v1/lessons/{lesson_id}/offline-package.json" in SPEC["paths"]
    # And it is not a LessonDetailResponse: the variants are nested and the
    # segment key is "key", so a client validating it as a lesson detail
    # would reject a correct package.
    segment = schemas["OfflinePackageSegment"]["properties"]
    assert "key" in segment
    assert "modalityVariants" in segment
    assert "segmentKey" not in segment


def test_b60_the_builder_validates_through_that_schema() -> None:
    from nevo.api.product_learning import _offline_package_payload

    source = inspect.getsource(_offline_package_payload)

    # So the shape the spec publishes is the shape that ships.
    assert "OfflinePackage.model_validate" in source


def test_b62_every_student_notification_has_a_student_path() -> None:
    from nevo.domain.accounts.vocabulary import (
        STUDENT_NOTIFICATION_SHAPES,
        STUDENT_NOTIFICATION_TYPES,
    )

    assert {item.value for item in STUDENT_NOTIFICATION_TYPES} == set(STUDENT_NOTIFICATION_SHAPES)
    for name, shape in STUDENT_NOTIFICATION_SHAPES.items():
        # Any other value renders as a row with no link.
        assert shape.navigates_to.startswith("/student/"), name
        assert shape.title.strip(), name


def test_b62_the_titles_are_frame_28s_words() -> None:
    from nevo.domain.accounts.vocabulary import STUDENT_NOTIFICATION_SHAPES

    assert STUDENT_NOTIFICATION_SHAPES["lesson_assigned"].title == "A new lesson is ready for you"
    assert "sent you a message" in STUDENT_NOTIFICATION_SHAPES["teacher_replied"].title


def test_b66_the_tenant_spec_exists_and_names_the_probe_handle() -> None:
    from pathlib import Path

    spec = Path(__file__).resolve().parents[1] / "docs" / "test-tenant-spec.md"
    text = spec.read_text()

    assert "NV-E2E000" in text
    # The school code is deliberately not a fixed point: a hardcoded one has
    # already broken CI once.
    assert "not a fixed point" in text


def test_b50_a_true_recall_always_strengthened_the_schedule() -> None:
    """recallSuccessful: true means the interval lengthened. Ask B50.

    Olayinka asked whether "You've got this one more firmly now" is safe to
    show on a true, or whether after_hint and second_attempt could return true
    without the schedule moving. Two separate guarantees answer it, and both
    are pinned here because the screen says something to a child on the back
    of them.
    """

    from datetime import UTC, datetime
    from uuid import uuid4

    from nevo.api.scheduler import RECALLED, ReviewOutcome
    from nevo.scheduler.fsrs import initial_schedule, update_schedule

    # One: only an unaided first attempt scores as recall at all.
    assert RECALLED == frozenset({ReviewOutcome.FIRST_TIME})
    for outcome in (ReviewOutcome.AFTER_HINT, ReviewOutcome.SECOND_ATTEMPT):
        assert outcome not in RECALLED

    # Two: a recall always strictly increases stability, which is what the due
    # date is derived from - so a true cannot come back with the interval
    # unchanged or shorter. Checked at the hardest difficulty the model
    # allows, which is where the stability gain is smallest.
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    schedule = initial_schedule(
        student_id=uuid4(), concept_id=uuid4(), recall_successful=True, reviewed_at=now
    )
    for _ in range(13):
        schedule = update_schedule(current=schedule, recall_successful=False, reviewed_at=now)
    assert schedule.difficulty >= 10
    strengthened = update_schedule(current=schedule, recall_successful=True, reviewed_at=now)
    assert strengthened.stability > schedule.stability
    assert strengthened.difficulty < schedule.difficulty
