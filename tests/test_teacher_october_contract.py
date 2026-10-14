from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from nevo.api import frontend_unblockers, product_learning
from nevo.api.insights import _pulse_label
from nevo.domain.accounts.vocabulary import UserRole
from nevo.main import app


@pytest.mark.asyncio
async def test_class_teacher_can_read_profile_without_support_grant(monkeypatch):
    student_id = uuid4()
    actor = SimpleNamespace(role=UserRole.TEACHER)
    access = AsyncMock(return_value=actor)
    grant = AsyncMock()
    monkeypatch.setattr(product_learning, "require_student_access", access)
    monkeypatch.setattr(product_learning, "require_learning_support_if_admin", grant)
    student = SimpleNamespace(
        id=student_id, first_name="Amara", last_name="Demo", age_band=None, date_of_birth=None
    )
    session = SimpleNamespace(
        get=AsyncMock(return_value=student), scalar=AsyncMock(side_effect=[None, 0])
    )
    result = await product_learning.student_profile(student_id, SimpleNamespace(), session)
    assert result["student"]["id"] == str(student_id)
    access.assert_awaited_once()
    grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_class_teacher_can_acknowledge_own_pupils_flag(monkeypatch):
    actor = SimpleNamespace(id=uuid4(), role=UserRole.TEACHER)
    flag = SimpleNamespace(
        id=uuid4(),
        student_id=uuid4(),
        acknowledged_at=None,
        acknowledged_by=None,
        flag_type=SimpleNamespace(value="sudden_change"),
        description="Learning changed",
        generated_at=datetime.now(UTC),
        evidence_series=[],
        action_targets=[],
    )
    grant = AsyncMock()
    access = AsyncMock()
    monkeypatch.setattr(frontend_unblockers, "actor_user", AsyncMock(return_value=actor))
    monkeypatch.setattr(frontend_unblockers, "require_student_access", access)
    monkeypatch.setattr(frontend_unblockers, "require_learning_support", grant)
    monkeypatch.setattr(frontend_unblockers, "_display_name", lambda _: "Teacher")
    session = SimpleNamespace(get=AsyncMock(side_effect=[flag, actor]), commit=AsyncMock())
    result = await frontend_unblockers.acknowledge_flag(
        flag.id, SimpleNamespace(role="teacher"), session
    )
    assert result["acknowledged"] is True
    access.assert_awaited_once()
    grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_teacher_cannot_acknowledge_an_unassigned_pupil(monkeypatch):
    actor = SimpleNamespace(id=uuid4(), role=UserRole.TEACHER)
    flag = SimpleNamespace(student_id=uuid4())
    monkeypatch.setattr(frontend_unblockers, "actor_user", AsyncMock(return_value=actor))
    monkeypatch.setattr(
        frontend_unblockers,
        "require_student_access",
        AsyncMock(side_effect=HTTPException(404, "Student not found")),
    )
    session = SimpleNamespace(get=AsyncMock(return_value=flag), commit=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await frontend_unblockers.acknowledge_flag(
            uuid4(), SimpleNamespace(role="teacher"), session
        )
    assert error.value.status_code == 404
    session.commit.assert_not_awaited()


def test_new_teacher_fields_are_typed():
    schemas = app.openapi()["components"]["schemas"]
    assert {"adminSupportRequestOpen", "adminSupportRequestedAt"} <= set(
        schemas["ClassStudentResponse"]["properties"]
    )
    assert {"engagementLabel", "comprehensionLabel", "focusLabel"} <= set(
        schemas["ClassLearningPulseResponse"]["properties"]
    )
    assert "note" in schemas["AdminSupportRequestBody"]["properties"]


@pytest.mark.parametrize(
    "score,label",
    [
        (None, "Still gathering a picture"),
        (49, "May benefit from support"),
        (50, "Mixed"),
        (74, "Mixed"),
        (75, "Steady"),
    ],
)
def test_pulse_words_use_server_boundaries(score, label):
    assert _pulse_label(score) == label


@pytest.mark.asyncio
async def test_message_notifications_link_to_the_specific_thread():
    teacher = SimpleNamespace(id=uuid4(), role=UserRole.TEACHER)
    sender = SimpleNamespace(id=uuid4(), role=UserRole.STUDENT)
    thread = SimpleNamespace(id=uuid4(), school_id=uuid4(), student_id=sender.id)
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[teacher]),
        scalar=AsyncMock(return_value=thread.id),
        add=Mock(),
    )
    await frontend_unblockers._notify_thread_message(session, thread, sender)
    notification = session.add.call_args.args[0]
    assert notification.recipient_id == teacher.id
    assert notification.navigates_to == f"/teacher/connect?thread={thread.id}"


@pytest.mark.asyncio
async def test_teacher_reply_keeps_student_notification_on_student_surface():
    sender = SimpleNamespace(id=uuid4(), role=UserRole.TEACHER)
    thread = SimpleNamespace(id=uuid4(), school_id=uuid4(), student_id=uuid4())
    session = SimpleNamespace(scalars=AsyncMock(return_value=[]), add=Mock())
    await frontend_unblockers._notify_thread_message(session, thread, sender)
    notification = session.add.call_args.args[0]
    assert notification.recipient_id == thread.student_id
    assert notification.navigates_to == f"/student/connect?thread={thread.id}"
